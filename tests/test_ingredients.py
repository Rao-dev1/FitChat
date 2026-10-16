import pytest

from app.llm.fake import ScriptedLLM, call, say
from app.models import Food, Ingredient, MealLog
from app.seed.loader import seed_all
from app.services import ingredients as ing
from app.services import nutrition as nut
from app.services.textmatch import norm


# ---- the case that started this: "300 g rajma" must come from a table, not from the model's guess ----------
def test_300g_cooked_rajma_is_computed_from_the_table(db):
    r = nut.log_item(db, "rajma", grams=300)
    assert r["logged"] and not r["estimated"] and r["source"] == "ingredient"
    assert (r["calories"], r["protein_g"]) == (381.0, 26.1)
    assert "per 100 g" in r["summary"] and "127" in r["summary"]
    assert nut.remaining(db)["calories_eaten"] == 381


@pytest.mark.parametrize("phrase", ["rajmi", "cooked rajma beans", "kidney beans", "Boiled Rajma", "rajma beans"])
def test_many_ways_of_saying_it_reach_the_same_row(db, phrase):
    r = nut.log_item(db, phrase, grams=100)
    assert r["matched_as"] == "Rajma, boiled" and r["calories"] == 127


def test_dry_and_cooked_are_different_rows(db):
    assert nut.log_item(db, "dry rajma", grams=100)["calories"] == 335
    assert nut.log_item(db, "100 g dry rajma beans", grams=100)["match"] == "loose"


def test_rajma_sabji_is_the_curry_dish_not_plain_beans(db):
    r = nut.log_item(db, "rajma sabji", grams=300)  # 2 x 150 g katori of the curry
    assert r["source"] == "table" and r["matched_as"] == "Rajma curry" and r["quantity"] == 2


def test_countable_ingredients_use_piece_weight(db):
    r = nut.log_item(db, "eggs", 2)
    assert r["source"] == "ingredient" or r["source"] == "table"
    assert r["protein_g"] >= 12


def test_ingredient_without_weight_is_not_guessed(db):
    r = nut.log_item(db, "cooked rajma")
    assert r["logged"] is False and "grams" in r["reason"]
    assert nut.daily_totals(db)["entries"] == 0


def test_vague_name_without_amount_does_not_pick_an_ingredient(db):
    r = nut.log_item(db, "chicken sandwich")  # contains "chicken" but is another food
    assert r["logged"] is False and "total_calories" in r["reason"]


def test_absurd_weight_is_rejected(db):
    with pytest.raises(ValueError):
        nut.log_item(db, "rice", grams=6000)


# ---- dishes built from ingredients ------------------------------------------------------------------------
def test_home_made_dish_is_summed_in_code(db):
    parts = [{"name": "cooked rajma", "grams": 200}, {"name": "onion", "grams": 50}, {"name": "oil", "grams": 14}]
    r = nut.log_item(db, "rajma sabji (home-made)", ingredients=parts, grams=300)
    assert r["logged"] and r["estimated"] and r["source"] == "ingredients"
    assert r["calories"] == pytest.approx(200 * 1.27 + 50 * 0.40 + 14 * 8.84, abs=0.2)
    assert r["protein_g"] == pytest.approx(200 * 0.087 + 50 * 0.011, abs=0.2)
    assert len(r["breakdown"]) == 3 and "ESTIMATE" in r["summary"] and "14 g cooking oil" in r["summary"]
    assert db.query(MealLog).count() == 1


def test_dish_with_an_unknown_ingredient_logs_nothing(db):
    r = nut.log_item(db, "mystery stew", ingredients=[{"name": "rajma", "grams": 100}, {"name": "unobtainium", "grams": 10}])
    assert r["logged"] is False and "unobtainium" in r["reason"]
    assert db.query(MealLog).count() == 0


def test_lookup_returns_per_100g_and_totals(db):
    out = ing.lookup(db, [{"name": "paneer", "grams": 100}, {"name": "rajma", "grams": 300}, {"name": "zzz"}])
    assert out["items"][0]["amount"]["protein_g"] == 18
    assert out["items"][1]["per_100g"]["calories"] == 127
    assert out["items"][2]["found"] is False
    assert out["total"]["calories"] == pytest.approx(265 + 381, abs=0.1)


def test_lookup_suggests_close_names(db):
    out = ing.lookup(db, [{"name": "kidney curry"}])
    assert not out["items"][0]["found"] and "Rajma, boiled" in out["items"][0]["did_you_mean"]


# ---- table integrity --------------------------------------------------------------------------------------
def test_table_has_no_ambiguous_names_or_nonsense_values(db):
    seen = {}
    for row in db.query(Ingredient):
        for n in [row.name, *row.aliases]:
            key = norm(n)
            assert seen.setdefault(key, row.name) == row.name, f"'{n}' used by {seen[key]} and {row.name}"
        # Atwater check: kcal should be close to 4P + 4C + 9F (alcohol/fibre make small gaps)
        est = 4 * row.protein_100g + 4 * row.carbs_100g + 9 * row.fat_100g
        assert abs(est - row.calories_100g) <= max(35, 0.15 * row.calories_100g), (row.name, est, row.calories_100g)
        assert 0 <= row.protein_100g <= 100 and row.calories_100g <= 900
    assert db.query(Ingredient).count() >= 85


def test_seeding_twice_keeps_user_edits_but_refreshes_untouched_rows(db):
    n = db.query(Ingredient).count()
    mine = db.query(Ingredient).filter_by(name="Paneer").one()
    mine.protein_100g, mine.source = 22, "user"
    other = db.query(Ingredient).filter_by(name="Tofu").one()
    other.protein_100g = 1
    db.commit()
    seed_all(db)
    assert db.query(Ingredient).count() == n
    assert db.query(Ingredient).filter_by(name="Paneer").one().protein_100g == 22
    assert db.query(Ingredient).filter_by(name="Tofu").one().protein_100g == 9


def test_old_database_with_plain_rajma_food_is_renamed(db):
    f = db.query(Food).filter_by(name="Rajma curry").one()
    f.name, f.aliases = "Rajma", []
    db.commit()
    seed_all(db)
    f = db.query(Food).filter_by(name="Rajma curry").one()
    assert "rajma sabji" in f.aliases and db.query(Food).filter_by(name="Rajma").count() == 0


# ---- through the chat pipeline ---------------------------------------------------------------------------
def test_chat_logs_300g_rajma_from_table_and_model_sees_exact_summary(client, db):
    llm = ScriptedLLM([call("log_food", items=[{"name": "rajmi", "grams": 300}]), say("Logged.")])
    client.set_llm(llm)
    client.post("/api/chat", json={"message": "i added 300g rajmi"})
    row = db.query(MealLog).one()
    assert (row.calories, row.protein_g, row.estimated) == (381.0, 26.1, False)
    shown = llm.calls[1][-1].tool_results[0].result
    assert "381 kcal, 26.1 g protein" in shown["results"][0]["summary"]
    assert "381 kcal and 26.1 g protein eaten" in shown["summary"]


def test_chat_lookup_tool_answers_without_logging(client, db):
    llm = ScriptedLLM([call("lookup_nutrition", items=[{"name": "whey", "grams": 30}]), say("24 g.")])
    client.set_llm(llm)
    client.post("/api/chat", json={"message": "protein in a scoop of whey?"})
    assert db.query(MealLog).count() == 0
    assert llm.calls[1][-1].tool_results[0].result["items"][0]["amount"]["protein_g"] == 24


# ---- Add food screen: log by weight without the language model --------------------------------------------
def test_ingredient_list_endpoint_searches_names_and_aliases(client):
    rows = client.get("/api/ingredients", params={"q": "rajmi"}).json()
    assert [r["name"] for r in rows] == ["Rajma, boiled"] and rows[0]["protein_100g"] == 8.7
    assert "rajmi" in rows[0]["aliases"]
    assert len(client.get("/api/ingredients").json()) >= 85


def test_log_weighed_endpoint_matches_chat_numbers_and_updates_remaining(client, db):
    rid = client.get("/api/ingredients", params={"q": "rajmi"}).json()[0]["id"]
    r = client.post("/api/meals/weighed", json={"ingredient_id": rid, "grams": 300})
    assert r.status_code == 201
    body = r.json()
    assert (body["calories"], body["protein_g"], body["estimated"]) == (381.0, 26.1, False)
    assert body["remaining"]["calories_eaten"] == 381
    assert db.query(MealLog).one().food_name == "Rajma, boiled (300 g)"


def test_log_weighed_rejects_bad_input(client, db):
    rid = client.get("/api/ingredients").json()[0]["id"]
    assert client.post("/api/meals/weighed", json={"ingredient_id": rid, "grams": 0}).status_code == 422
    assert client.post("/api/meals/weighed", json={"ingredient_id": rid, "grams": 99999}).status_code == 422
    assert client.post("/api/meals/weighed", json={"ingredient_id": 987654, "grams": 100}).status_code == 404
    assert db.query(MealLog).count() == 0
