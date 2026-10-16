from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text

from app.llm.fake import ScriptedLLM, call, say
from app.migrate import ensure_columns
from app.models import BowelLog
from app.services import nutrition as nut


def test_water_add_total_delete_and_limits(client, db):
    assert client.post("/api/water", json={"ml": 250}).status_code == 201
    r = client.post("/api/water", json={"ml": 500}).json()
    assert r["water_ml"] == 750 and r["gut"]["water_entries"][-1]["ml"] == 500
    for bad in (0, 10, 5000, -100):
        assert client.post("/api/water", json={"ml": bad}).status_code == 422
    assert client.delete(f"/api/water/{r['gut']['water_entries'][0]['id']}").json()["gut"]["water_ml"] == 500
    assert client.delete("/api/water/9999").status_code == 404
    fut = (date.today() + timedelta(days=1)).isoformat()
    assert client.post("/api/water", json={"ml": 250, "day": fut}).status_code == 422


def test_daily_water_cap(client, db):
    for _ in range(5):
        assert client.post("/api/water", json={"ml": 2000}).status_code == 201
    assert client.post("/api/water", json={"ml": 250}).status_code == 422  # would exceed 10 L


def test_fibre_comes_from_food_and_ingredient_tables(client, db):
    nut.log_item(db, "Rajma curry", 2)                    # 2 x 6 g
    nut.log_item(db, "Oats, dry", grams=50)               # 5 g
    nut.log_item(db, "Mystery", totals={"calories": 100, "protein_g": 5, "fibre_g": 3})
    t = nut.daily_totals(db)
    assert t["fibre_g"] == 12 + 5 + 3
    assert nut.remaining(db)["fibre_remaining_g"] == 30 - 20


def test_dish_from_ingredients_sums_fibre(db):
    r = nut.log_item(db, "my bowl", ingredients=[{"name": "Rajma, dry", "grams": 40}, {"name": "Onion", "grams": 100}])
    assert r["logged"] and nut.daily_totals(db)["fibre_g"] == 10 + 1.7


def test_bowel_validation_and_meaning(client, db):
    assert client.post("/api/bowel", json={"bristol": 4}).json()["meaning"].startswith("Smooth")
    for bad in (0, 8):
        assert client.post("/api/bowel", json={"bristol": bad}).status_code == 422
    assert client.post("/api/bowel", json={"bristol": 3, "note": "x" * 300}).status_code == 422


def test_hints_normal_hard_loose_and_doctor(client, db):
    assert client.get("/api/gut").json()["days_since_bowel"] is None
    client.post("/api/bowel", json={"bristol": 4}); client.post("/api/bowel", json={"bristol": 3})
    g = client.get("/api/gut").json()
    assert any("look normal" in h for h in g["hints"]) and g["alert"] == "none"
    for _ in range(2):
        client.post("/api/bowel", json={"bristol": 1})
    assert any("hard" in h for h in client.get("/api/gut").json()["hints"])
    db.query(BowelLog).delete(); db.commit()
    for _ in range(2):
        client.post("/api/bowel", json={"bristol": 7})
    assert any("loose" in h for h in client.get("/api/gut").json()["hints"])
    client.post("/api/bowel", json={"bristol": 3, "warning_signs": True})
    g = client.get("/api/gut").json()
    assert g["alert"] == "see_doctor" and "see a doctor" in " ".join(g["hints"])


def test_days_since_bowel_hint(client, db):
    db.add(BowelLog(day=date.today() - timedelta(days=4), bristol=3)); db.commit()
    g = client.get("/api/gut").json()
    assert g["days_since_bowel"] == 4 and any("4 days" in h for h in g["hints"])


def test_low_fibre_high_protein_hint_and_fibre_foods(client, db):
    nut.log_item(db, "Whey", totals={"calories": 400, "protein_g": 100})
    g = client.get("/api/gut").json()
    assert any("High protein with low fibre" in h for h in g["hints"]) and g["fibre_foods"]
    assert all(f["fibre_g"] >= 3 for f in g["fibre_foods"])


def test_targets_editable_and_validated(client):
    r = client.put("/api/profile", json={"water_target_ml": 3500, "fibre_target_g": 35}).json()
    assert r["water_target_ml"] == 3500 and r["fibre_target_g"] == 35
    assert client.put("/api/profile", json={"water_target_ml": 50}).status_code == 422
    assert client.put("/api/profile", json={"fibre_target_g": 500}).status_code == 422
    assert client.get("/api/summary/today").json()["gut"]["water_target_ml"] == 3500


def test_old_database_is_upgraded_without_losing_rows():
    eng = create_engine("sqlite://")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE meal_logs (id INTEGER PRIMARY KEY, food_name TEXT, calories FLOAT)"))
        c.execute(text("INSERT INTO meal_logs (food_name, calories) VALUES ('roti', 110)"))
        c.execute(text("CREATE TABLE profile (id INTEGER PRIMARY KEY, goal TEXT)"))
    added = ensure_columns(eng)
    assert "meal_logs.fibre_g" in added and "profile.water_target_ml" in added and "profile.gym_days_goal" in added
    with eng.begin() as c:
        assert c.execute(text("SELECT food_name, calories, fibre_g FROM meal_logs")).one() == ("roti", 110, 0)
    assert ensure_columns(eng) == []  # idempotent


def test_coach_tools_for_water_and_stool(client, db):
    client.set_llm(ScriptedLLM([call("log_water", ml=500), call("log_stool", bristol=2), call("get_digestion_status"), say("ok")]))
    assert client.post("/api/chat", json={"message": "500 ml water, hard stool"}).status_code == 200
    g = client.get("/api/gut").json()
    assert g["water_ml"] == 500 and g["bowel_today"][0]["bristol"] == 2
    client.set_llm(ScriptedLLM([call("log_stool", bristol=9), say("ok")]))
    client.post("/api/chat", json={"message": "x"})
    assert len(client.get("/api/gut").json()["bowel_today"]) == 1  # invalid type was refused
