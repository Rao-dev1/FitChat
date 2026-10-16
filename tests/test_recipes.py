import pytest

from app.llm.fake import ScriptedLLM, call, say
from app.models import Food, Recipe
from app.services import ingredients as ing
from app.services import nutrition as nut

RAJMA = [
    {"name": "rajma", "grams": 200},
    {"name": "onion", "amount": 2, "unit": "pieces"},
    {"name": "tomato", "grams": 200},
    {"name": "oil", "amount": 2, "unit": "tbsp"},
    {"name": "salt", "amount": 1, "unit": "tsp"},
    {"name": "water", "amount": 3, "unit": "cup"},
]


def test_units_convert_with_known_densities(db):
    r = ing.compose_ex(db, [{"name": "oil", "amount": 2, "unit": "tbsp"}, {"name": "milk", "amount": 1, "unit": "glass"},
                            {"name": "sugar", "amount": 1, "unit": "tsp"}, {"name": "egg", "amount": 2, "unit": "pieces"}])
    g = {ln["ingredient"]: ln["grams"] for ln in r["lines"]}
    assert g["Cooking oil"] == pytest.approx(26.9, abs=0.1) and g["Milk, toned"] == pytest.approx(257.5, abs=0.1)
    assert g["Sugar"] == pytest.approx(4.2, abs=0.1) and g["Egg, whole"] == 100
    assert r["problems"] == []


def test_volume_of_unknown_density_is_refused_not_guessed(db):
    r = ing.compose_ex(db, [{"name": "paneer", "amount": 1, "unit": "cup"}])
    assert r["totals"] is None and "Give its weight in grams" in r["problems"][0]
    assert ing.compose_ex(db, [{"name": "paneer", "amount": 1, "unit": "bunch"}])["problems"]
    assert ing.compose_ex(db, [{"name": "paneer"}])["problems"]  # no amount at all


def test_recipe_mode_defaults_to_raw_and_says_so(db):
    r = ing.compose_ex(db, [{"name": "rajma", "grams": 200}, {"name": "rice", "grams": 100}, {"name": "chicken", "grams": 500}],
                       raw_default=True)
    names = {ln["input"]: ln["ingredient"] for ln in r["lines"]}
    assert names == {"rajma": "Rajma, dry", "rice": "Rice, dry", "chicken": "Chicken breast, raw"}
    assert len(r["assumptions"]) == 3
    c = ing.compose_ex(db, [{"name": "cooked rajma", "grams": 200}, {"name": "cooked rice", "grams": 100}], raw_default=True)
    assert [ln["ingredient"] for ln in c["lines"]] == ["Rajma, boiled", "Rice, cooked"] and c["assumptions"] == []
    # outside recipe mode a bare name still means as eaten (cooked)
    assert ing.compose_ex(db, [{"name": "rajma", "grams": 200}])["lines"][0]["ingredient"] == "Rajma, boiled"


def test_ambiguous_dal_asks_instead_of_guessing(db):
    r = ing.compose_ex(db, [{"name": "dal", "grams": 100}], raw_default=True)
    assert r["totals"] is None and "Toor dal, dry" in r["problems"][0]
    ok = ing.compose_ex(db, [{"name": "toor dal", "grams": 100}], raw_default=True)
    assert ok["lines"][0]["ingredient"] == "Toor dal, dry"


def test_spices_and_water_are_ignored_but_listed_big_unknowns_are_not(db):
    r = ing.compose_ex(db, [{"name": "garam masala", "amount": 1, "unit": "tsp"}, {"name": "water", "amount": 2, "unit": "l"},
                            {"name": "salt"}, {"name": "rice", "grams": 50}], raw_default=True)
    assert [i["name"] for i in r["ignored"]] == ["garam masala", "water", "salt"] and r["problems"] == []
    big = ing.compose_ex(db, [{"name": "garlic", "grams": 80}])
    assert big["totals"] is None and "not in the ingredient table" in big["problems"][0]


def test_analyze_per_serving_math_and_confidence(client):
    r = client.post("/api/recipes/preview", json={"ingredients": RAJMA, "servings": 4, "cooked_weight_g": 1200}).json()
    assert r["ok"] and r["serving_g"] == 300
    t = r["total"]
    # 200 g dry rajma (335/100 g) + 220 g onion + 200 g tomato + 26.9 g oil
    assert t["calories"] == pytest.approx(200 * 3.35 + 220 * 0.4 + 200 * 0.18 + 26.9 * 8.84, abs=6)
    assert r["per_serving"]["calories"] == pytest.approx(t["calories"] / 4, abs=0.2)
    assert r["per_100g_cooked"]["calories"] == pytest.approx(t["calories"] / 12, abs=0.2)
    assert r["confidence"] == "medium" and any("raw/dry" in a for a in r["assumptions"])
    assert {i["name"] for i in r["ignored"]} == {"salt", "water"} and r["per_serving"]["fibre_g"] > 5


def test_preview_problems_and_validation(client):
    p = client.post("/api/recipes/preview", json={"ingredients": [{"name": "quinoa", "grams": 100}], "servings": 2}).json()
    assert p["ok"] is False and "not in the ingredient table" in p["problems"][0]
    assert client.post("/api/recipes/preview", json={"ingredients": RAJMA, "servings": 0}).status_code == 422
    assert client.post("/api/recipes/preview", json={"ingredients": RAJMA, "servings": 100}).status_code == 422
    assert client.post("/api/recipes/preview", json={"ingredients": RAJMA, "cooked_weight_g": 5}).status_code == 422
    assert client.post("/api/recipes/preview", json={"ingredients": []}).status_code == 422
    assert client.post("/api/recipes/preview", json={"ingredients": [{"name": "rice", "grams": -5}]}).status_code == 422
    huge = [{"name": "cooking oil", "grams": 4000}]
    assert client.post("/api/recipes/preview", json={"ingredients": huge, "servings": 1}).status_code == 422


def test_save_creates_food_row_and_logging_by_name_and_grams(client, db):
    r = client.post("/api/recipes", json={"name": "My rajma masala", "aliases": ["ghar ka rajma"], "ingredients": RAJMA,
                                          "servings": 4, "cooked_weight_g": 1200})
    assert r.status_code == 201
    body = r.json()
    food = db.get(Food, body["food_id"])
    assert food.source == "recipe" and food.serving == "1 serving (about 300 g)"
    per = body["per_serving"]["calories"]
    # one serving by name
    log = nut.log_item(db, "my rajma masala", 1)
    assert log["logged"] and log["calories"] == pytest.approx(per, abs=0.1) and not log["estimated"]
    # 150 g = half a serving, by alias
    half = nut.log_item(db, "ghar ka rajma", grams=150)
    assert half["calories"] == pytest.approx(per / 2, abs=0.2)
    assert nut.daily_totals(db)["fibre_g"] > 0
    assert any(f["source"] == "recipe" for f in client.get("/api/foods").json())


def test_duplicate_names_blocked_and_update_recomputes(client, db):
    base = {"ingredients": RAJMA, "servings": 4}
    assert client.post("/api/recipes", json={"name": "Dal", **base}).status_code == 409  # a starter food
    rid = client.post("/api/recipes", json={"name": "Pot A", **base}).json()["id"]
    assert client.post("/api/recipes", json={"name": "pot a", **base}).status_code == 409
    before = client.get("/api/recipes").json()[0]["per_serving"]["calories"]
    up = client.put(f"/api/recipes/{rid}", json={"name": "Pot A", "ingredients": RAJMA, "servings": 2})
    assert up.status_code == 200 and up.json()["per_serving"]["calories"] == pytest.approx(before * 2, abs=0.3)
    assert db.query(Food).filter(Food.name == "Pot A").count() == 1
    assert client.put("/api/recipes/999", json={"name": "x", **base}).status_code == 404


def test_recipe_food_cannot_be_edited_as_a_plain_dish_and_delete_removes_both(client, db):
    rec = client.post("/api/recipes", json={"name": "Pot B", "ingredients": RAJMA, "servings": 4}).json()
    put = client.put(f"/api/foods/{rec['food_id']}", json={"name": "Pot B", "serving": "1", "calories": 1, "protein_g": 1})
    assert put.status_code == 409 and "Recipes" in put.json()["detail"]
    nut.log_item(db, "Pot B", 1)
    assert client.delete(f"/api/foods/{rec['food_id']}").status_code == 204
    assert db.query(Recipe).count() == 0 and db.query(Food).filter(Food.name == "Pot B").count() == 0
    assert nut.daily_totals(db)["entries"] == 1  # earlier log entries are snapshots and stay
    rec2 = client.post("/api/recipes", json={"name": "Pot C", "ingredients": RAJMA, "servings": 4}).json()
    assert client.delete(f"/api/recipes/{rec2['id']}").status_code == 204
    assert client.delete(f"/api/recipes/{rec2['id']}").status_code == 404


def test_coach_flow_analyze_then_save_then_log(client, db):
    lines = [{"name": "paneer", "grams": 200}, {"name": "onion", "grams": 100}, {"name": "oil", "amount": 1, "unit": "tbsp"}]
    client.set_llm(ScriptedLLM([
        call("analyze_recipe", ingredients=lines, servings=2),
        call("save_recipe", name="Paneer bhurji home", ingredients=lines, servings=2),
        call("log_food", items=[{"name": "Paneer bhurji home", "quantity": 1}]),
        say("done")]))
    assert client.post("/api/chat", json={"message": "I make bhurji: 200 g paneer, 1 onion, 1 tbsp oil, 2 servings. Ate one."}).status_code == 200
    rec = client.get("/api/recipes").json()
    assert len(rec) == 1 and rec[0]["name"] == "Paneer bhurji home"
    m = nut.daily_totals(db)["items"][0]
    assert m["food"] == "Paneer bhurji home" and m["kcal"] == pytest.approx(rec[0]["per_serving"]["calories"], abs=0.1)
    # a bad recipe through the coach does not save and does not crash
    client.set_llm(ScriptedLLM([call("save_recipe", name="Bad", ingredients=[{"name": "unobtainium", "grams": 5}]), say("ok")]))
    client.post("/api/chat", json={"message": "save it"})
    assert len(client.get("/api/recipes").json()) == 1


def test_log_food_dish_lines_accept_units(db):
    r = nut.log_item(db, "chai", ingredients=[{"name": "milk", "amount": 1, "unit": "cup"}, {"name": "sugar", "amount": 1, "unit": "tsp"}])
    assert r["logged"] and 140 < r["calories"] < 200
