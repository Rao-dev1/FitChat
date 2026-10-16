import time
from collections import Counter

from app.seed.foods import FOODS
from app.seed.shopping import DISH_SHOPPING
from app.services import mealprep as mp


def test_every_starter_dish_has_shopping_entry():
    assert {f[0] for f in FOODS} <= set(DISH_SHOPPING)


def test_week_plan_shape_and_speed(client):
    t = time.time()
    r = client.post("/api/mealprep", json={}).json()["plan"]
    assert time.time() - t < 20
    assert len(r["days"]) == 7 and all(len(d["slots"]) == 4 for d in r["days"])
    for d in r["days"]:
        assert abs(d["totals"]["calories"] - r["targets"]["calories"]) < 0.2 * r["targets"]["calories"]
        for s in d["slots"]:
            assert s["totals"]["calories"] <= 900 and all(i["servings"] <= 3 for i in s["items"])


def test_variety_across_days(client):
    r = client.post("/api/mealprep", json={}).json()["plan"]
    c = Counter(i["food"] for d in r["days"] for s in d["slots"] for i in s["items"])
    assert len(c) >= 14                         # not the same handful every day
    assert max(c.values()) <= 10


def test_saved_and_reshuffle_changes_plan(client):
    a = client.post("/api/mealprep", json={}).json()["plan"]
    assert client.get("/api/mealprep").json()["plan"]["start"] == a["start"]
    b = client.post("/api/mealprep", json={"reshuffle": True}).json()["plan"]
    names = lambda p: [i["food"] for d in p["days"] for s in d["slots"] for i in s["items"]]  # noqa: E731
    assert names(a) != names(b)
    assert client.get("/api/mealprep").json()["plan"]["summary"] == b["summary"]  # only the latest is kept


def test_grocery_adds_up_and_groups(db):
    days = [{"slots": [{"items": [{"food": "Roti", "servings": 3}, {"food": "Dal", "servings": 1}, {"food": "Boiled egg", "servings": 2}]}]},
            {"slots": [{"items": [{"food": "Roti", "servings": 3}, {"food": "Dal", "servings": 2}]}]}]
    g = {x["aisle"]: {i["name"]: i for i in x["items"]} for x in mp.grocery(db, days)}
    assert g["Grains and flour"]["Wheat flour (atta)"]["qty"] == 35 * 6
    assert g["Pulses and soy"]["Toor dal"]["qty"] == 35 * 3
    assert g["Dairy and eggs"]["Eggs"]["text"] == "2 pcs"
    assert list(g)[0] == "Vegetables"  # aisle order is the shop order


def test_grocery_units_friendly():
    assert mp._friendly(1234, "g") == "1.25 kg"
    assert mp._friendly(212, "g") == "220 g"
    assert mp._friendly(2.2, "pcs") == "3 pcs"
    assert mp._friendly(1500, "ml") == "1.5 L"


def test_grocery_uses_recipe_ingredients(client, db):
    client.post("/api/recipes", json={"name": "Test rajma", "servings": 4, "ingredients": [
        {"name": "rajma", "grams": 200}, {"name": "onion", "grams": 100}]})
    days = [{"slots": [{"items": [{"food": "Test rajma", "servings": 2}]}]}]
    flat = {i["name"]: i for x in mp.grocery(db, days) for i in x["items"]}
    assert flat["Rajma"]["qty"] == 100 and flat["Onion"]["qty"] == 50


def test_unknown_food_listed_as_itself(db):
    g = mp.grocery(db, [{"slots": [{"items": [{"food": "Mystery dish", "servings": 2}]}]}])
    assert "Mystery dish" in g[0]["items"][0]["name"] and g[0]["aisle"] == "Other"


def test_grocery_text(client):
    r = client.post("/api/mealprep", json={"days": 2}).json()["plan"]
    assert "VEGETABLES" in r["grocery_text"] or "GRAINS" in r["grocery_text"]


def test_coach_tools(client):
    from app.llm.fake import ScriptedLLM, call, say
    client.set_llm(ScriptedLLM([call("log_measurements", waist_cm=96.5), call("log_sleep_steps", sleep_h=7, steps=9000),
                                call("get_winter_arc"), call("get_body_progress"), call("plan_week", days=2), call("get_grocery_list"), say("ok")]))
    r = client.post("/api/chat", json={"message": "log my stuff"})
    assert r.status_code == 200
    assert client.get("/api/body").json()["measures"][-1]["waist_cm"] == 96.5
    assert client.get("/api/daystats").json()["today"]["steps"] == 9000
    assert client.get("/api/mealprep").json()["plan"]["days"].__len__() == 2
