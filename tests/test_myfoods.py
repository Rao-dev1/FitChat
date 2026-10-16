import httpx
import pytest

from app.llm.fake import ScriptedLLM, call, say
from app.models import Food, Ingredient, MealLog
from app.seed.loader import seed_all
from app.services import nutrition as nut
from app.services import openfoodfacts as off


def make(client, **kw):
    body = {"name": "Protein bhel", "calories": 180, "protein_g": 12, "carbs_g": 20, "fat_g": 5, **kw}
    return client.post("/api/ingredients", json=body)


# ---- adding your own ingredient -------------------------------------------------------------------------------
def test_add_per_100g_then_log_it_by_weight_and_through_the_coach(client, db):
    r = make(client, aliases=["bhel"])
    assert r.status_code == 201 and r.json()["source"] == "user" and r.json()["warnings"] == []
    rid = r.json()["id"]
    w = client.post("/api/meals/weighed", json={"ingredient_id": rid, "grams": 200}).json()
    assert (w["calories"], w["protein_g"]) == (360, 24)
    client.set_llm(ScriptedLLM([call("log_food", items=[{"name": "bhel", "grams": 100}]), say("ok")]))
    client.post("/api/chat", json={"message": "100 g bhel"})
    assert db.query(MealLog).count() == 2 and db.query(MealLog).all()[1].calories == 180


def test_per_serving_values_are_converted_using_the_serving_weight(client):
    r = client.post("/api/ingredients", json={
        "name": "Choco protein bar", "basis": "serving", "serving_g": 60, "serving_label": "1 bar",
        "calories": 210, "protein_g": 20, "carbs_g": 22, "fat_g": 7})
    j = r.json()
    assert r.status_code == 201 and (j["calories_100g"], j["protein_100g"]) == (350, 33.33)
    assert j["serving_g"] == 60 and j["serving_label"] == "1 bar"
    assert nut.log_item(_db(client), "choco protein bar", 2)["calories"] == 420


def _db(client):
    from app.db import get_db
    return client.app.dependency_overrides[get_db]()


def test_per_serving_without_a_weight_is_refused(client):
    r = client.post("/api/ingredients", json={"name": "X bar", "basis": "serving", "calories": 200, "protein_g": 10})
    assert r.status_code == 422 and "weight of one serving" in r.json()["detail"]


def test_values_that_look_like_per_serving_numbers_are_caught(client):
    r = make(client, name="Big meal", calories=650, protein_g=45, carbs_g=80, fat_g=20)  # sums to 145 g per 100 g
    assert r.status_code == 422 and "can't exceed 100 g" in r.json()["detail"]
    assert make(client, name="Super", calories=1200, protein_g=10).status_code == 422


def test_inconsistent_calories_are_saved_with_a_warning(client):
    r = make(client, name="Odd label", calories=50, protein_g=10, carbs_g=30, fat_g=20)
    assert r.status_code == 201 and r.json()["warnings"]


def test_duplicate_names_and_aliases_are_rejected_across_both_tables(client):
    assert make(client, name="Rajma, boiled").status_code == 409
    assert make(client, name="My rajma", aliases=["kidney beans"]).status_code == 409
    assert make(client, name="Roti").status_code == 409  # a dish already uses this name
    assert make(client, name="ROTI ").status_code == 409


# ---- editing and deleting ------------------------------------------------------------------------------------
def test_editing_a_builtin_row_makes_it_yours_and_survives_restart_seeding(client, db):
    rid = client.get("/api/ingredients", params={"q": "paneer"}).json()[0]["id"]
    r = client.put(f"/api/ingredients/{rid}", json={"name": "Paneer", "calories": 300, "protein_g": 20, "carbs_g": 3, "fat_g": 24,
                                                    "aliases": ["cottage cheese"]})
    assert r.status_code == 200 and r.json()["source"] == "user" and r.json()["calories_100g"] == 300
    seed_all(db)
    assert db.get(Ingredient, rid).calories_100g == 300


def test_edit_keeps_unchanged_aliases_even_if_another_table_shares_them(client):
    rid = client.get("/api/ingredients", params={"q": "roti, plain"}).json()[0]["id"]
    j = client.get("/api/ingredients", params={"q": "roti, plain"}).json()[0]
    r = client.put(f"/api/ingredients/{rid}", json={"name": j["name"], "aliases": j["aliases"], "calories": 280,
                                                    "protein_g": 8.3, "carbs_g": 50, "fat_g": 5, "serving_g": 40,
                                                    "serving_label": "1 medium roti"})
    assert r.status_code == 200, r.text


def test_delete_own_food_but_not_a_builtin_one(client, db):
    mine = make(client).json()["id"]
    assert client.delete(f"/api/ingredients/{mine}").status_code == 204
    builtin = client.get("/api/ingredients", params={"q": "paneer"}).json()[0]["id"]
    r = client.delete(f"/api/ingredients/{builtin}")
    assert r.status_code == 409 and "Built-in" in r.json()["detail"]
    assert client.delete("/api/ingredients/987654").status_code == 404


def test_deleting_a_food_keeps_past_meals(client, db):
    rid = make(client).json()["id"]
    client.post("/api/meals/weighed", json={"ingredient_id": rid, "grams": 100})
    client.delete(f"/api/ingredients/{rid}")
    assert db.query(MealLog).one().calories == 180
    assert nut.daily_totals(db)["calories"] == 180


# ---- dishes (per serving, no weight) -------------------------------------------------------------------------
def test_add_a_dish_per_serving_and_log_it_in_servings(client, db):
    r = client.post("/api/foods", json={"name": "Mess thali", "aliases": ["hostel thali"], "serving": "1 plate",
                                        "calories": 750, "protein_g": 22, "carbs_g": 110, "fat_g": 22})
    assert r.status_code == 201 and r.json()["source"] == "user"
    out = nut.log_item(db, "hostel thali", 2)
    assert out["source"] == "table" and out["calories"] == 1500
    assert client.put(f"/api/foods/{r.json()['id']}", json={"name": "Mess thali", "serving": "1 plate", "calories": 700,
                                                           "protein_g": 22}).json()["calories"] == 700
    assert client.delete(f"/api/foods/{r.json()['id']}").status_code == 204
    assert db.query(Food).filter_by(name="Mess thali").count() == 0


def test_dish_validation(client):
    assert client.post("/api/foods", json={"name": "Roti", "serving": "1", "calories": 1, "protein_g": 1}).status_code == 409
    assert client.post("/api/foods", json={"name": "Zero", "serving": "1", "calories": -1, "protein_g": 1}).status_code == 422
    builtin = client.get("/api/foods", params={"q": "roti"}).json()[0]
    assert client.delete(f"/api/foods/{builtin['id']}").status_code == 409


# ---- Open Food Facts -----------------------------------------------------------------------------------------
PAYLOAD = {"products": [
    {"code": "1", "product_name": "Greek Yogurt", "brands": "Acme, Other", "serving_quantity": "150", "serving_size": "150 g",
     "nutriments": {"energy-kcal_100g": 97, "proteins_100g": "9.5", "carbohydrates_100g": 3.9, "fat_100g": 5}},
    {"code": "2", "product_name": "Kilojoule only", "nutriments": {"energy_100g": 418.4, "proteins_100g": 4, "fat_100g": 2}},
    {"code": "3", "product_name": "No protein", "nutriments": {"energy-kcal_100g": 50}},
    {"code": "4", "product_name": "", "nutriments": {"energy-kcal_100g": 50, "proteins_100g": 1}},
    {"code": "5", "product_name": "Greek yogurt", "brands": "acme", "nutriments": {"energy-kcal_100g": 97, "proteins_100g": 9.5}},
    {"code": "6", "product_name": "Impossible", "nutriments": {"energy-kcal_100g": 5000, "proteins_100g": 9}},
    {"code": "7", "product_name": "Macros too big", "nutriments": {"energy-kcal_100g": 400, "proteins_100g": 60, "carbohydrates_100g": 60}},
]}


def test_parse_products_keeps_good_rows_and_drops_bad_ones():
    rows = off.parse_products(PAYLOAD)
    assert [r["name"] for r in rows] == ["Greek Yogurt", "Kilojoule only"]  # duplicate, incomplete and absurd rows dropped
    assert rows[0]["brand"] == "Acme" and rows[0]["serving_g"] == 150 and rows[0]["protein_100g"] == 9.5
    assert rows[1]["calories_100g"] == 100.0


def test_online_search_endpoint(client, monkeypatch):
    seen = {}

    def fake(params):
        seen.update(params)
        return PAYLOAD
    monkeypatch.setattr(off, "_fetch", fake)
    body = client.get("/api/online-foods", params={"q": "greek yogurt"}).json()
    assert seen["search_terms"] == "greek yogurt" and len(body["results"]) == 2 and "Open Food Facts" in body["source"]


@pytest.mark.parametrize("exc,text", [(httpx.ConnectError("x"), "Could not reach"),
                                      (ValueError("bad json"), "Could not reach")])
def test_online_search_failures_are_friendly(client, monkeypatch, exc, text):
    def boom(params):
        raise exc
    monkeypatch.setattr(off, "_fetch", boom)
    r = client.get("/api/online-foods", params={"q": "paneer"})
    assert r.status_code == 502 and text in r.json()["detail"]


def test_online_search_rate_limit_and_short_query(client, monkeypatch):
    def limited(params):
        raise httpx.HTTPStatusError("429", request=httpx.Request("GET", "http://x"), response=httpx.Response(429))
    monkeypatch.setattr(off, "_fetch", limited)
    assert "rate-limiting" in client.get("/api/online-foods", params={"q": "paneer"}).json()["detail"]
    assert client.get("/api/online-foods", params={"q": "a"}).status_code == 502


def test_saving_an_online_result_as_my_food(client):
    row = off.parse_products(PAYLOAD)[0]
    r = client.post("/api/ingredients", json={
        "name": f"{row['name']} ({row['brand']})", "calories": row["calories_100g"], "protein_g": row["protein_100g"],
        "carbs_g": row["carbs_100g"], "fat_g": row["fat_100g"], "serving_g": row["serving_g"],
        "serving_label": row["serving_label"], "source": "openfoodfacts"})
    assert r.status_code == 201 and r.json()["source"] == "openfoodfacts" and r.json()["serving_g"] == 150
