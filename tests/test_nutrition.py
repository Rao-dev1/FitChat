from app.services import nutrition as nut
from app.services import workouts as wk


def test_log_known_food_uses_table_and_scales_quantity(db):
    r = nut.log_item(db, "roti", 2)
    assert r["logged"] and not r["estimated"]
    assert r["calories"] == 220 and r["protein_g"] == 6.6


def test_alias_lookup(db):
    assert nut.find_food(db, "dahi").name == "Curd"


def test_unknown_food_needs_estimate(db):
    assert nut.log_item(db, "mystery thali")["logged"] is False
    r = nut.log_item(db, "mystery thali", 1, estimate={"calories": 600, "protein_g": 20})
    assert r["logged"] and r["estimated"]


def test_remaining_and_estimated_flag(db):
    nut.log_item(db, "mystery", 1, estimate={"calories": 500, "protein_g": 10})
    rem = nut.remaining(db)
    assert rem["calories_remaining"] == 2200 - 500
    assert rem["any_estimated_entries"] is True


def test_training_day_bonus(db):
    base = nut.remaining(db)["calorie_target"]
    wk.log_workout(db, "Barbell Curl", [{"reps": 10, "weight_kg": 20}] * 6)
    assert nut.remaining(db)["calorie_target"] == base + nut.TRAINING_DAY_CALORIE_BONUS


def test_suggestions_fit_remaining_budget(db):
    p = nut.get_profile(db)
    p.calorie_target = 400
    db.commit()
    s = nut.suggest_foods(db)
    assert s["suggestions"] and all(x["kcal"] <= 400 for x in s["suggestions"])


def test_no_suggestions_when_over_target(db):
    nut.log_item(db, "mystery", 1, estimate={"calories": 5000, "protein_g": 1})
    assert nut.suggest_foods(db)["suggestions"] == []


def test_invalid_quantity(db):
    import pytest
    with pytest.raises(ValueError):
        nut.log_item(db, "roti", 0)


# ---- regression: "300 g of my home-made rajma sabji" was logged as 3 table servings (510 kcal / 24 g) ----
import pytest  # noqa: E402


def test_custom_dish_totals_win_over_a_similarly_named_table_food(db):
    r = nut.log_item(db, "rajma sabji", grams=300, totals={"calories": 400, "protein_g": 16, "carbs_g": 45, "fat_g": 14})
    assert r["logged"] and r["estimated"] and r["source"] == "estimate" and r["matched_as"] is None
    assert (r["calories"], r["protein_g"]) == (400, 16)
    assert "ESTIMATE" in r["summary"] and "300 g" in r["summary"]
    rem = nut.remaining(db)
    assert rem["calories_eaten"] == 400 and rem["protein_eaten_g"] == 16 and rem["any_estimated_entries"]


def test_old_failure_case_per_serving_estimate_beats_loose_match(db):
    r = nut.log_item(db, "rajma curry homemade", 3, estimate={"calories": 90, "protein_g": 5})
    assert r["estimated"] and (r["calories"], r["protein_g"]) == (270, 15)  # was 510 / 24 from the table


def test_exact_table_match_still_uses_table_even_if_estimate_given(db):
    r = nut.log_item(db, "roti", 2, estimate={"calories": 999, "protein_g": 1})
    assert not r["estimated"] and r["calories"] == 220


def test_loose_match_without_estimate_uses_table_but_says_so(db):
    r = nut.log_item(db, "rajma curry homemade", 1)
    assert r["match"] == "loose" and r["matched_as"] == "Rajma curry" and "closest match" in r["summary"]


def test_whole_word_matching_only(db):
    assert nut.find_food(db, "dalia") is None  # used to match "Dal" by substring
    assert nut.find_food(db, "chicken") is None  # ambiguous (breast vs curry): never guess
    assert nut.find_food(db, "bhurji").name == "Paneer bhurji"


def test_grams_converted_using_table_serving_weight(db):
    r = nut.log_item(db, "dal", grams=300)  # 1 katori = 150 g -> 2 servings
    assert r["quantity"] == 2 and r["calories"] == 300 and r["protein_g"] == 16


def test_grams_for_food_without_serving_weight_is_not_guessed(db):
    r = nut.log_item(db, "poha", grams=250)  # "1 plate" has no weight
    assert r["logged"] is False and "total_calories" in r["reason"]


def test_implausible_totals_are_rejected(db):
    with pytest.raises(ValueError):
        nut.log_item(db, "x", totals={"calories": 27000, "protein_g": 10})
    with pytest.raises(ValueError):
        nut.log_item(db, "x", totals={"calories": -5, "protein_g": 10})
    assert nut.daily_totals(db)["entries"] == 0


def test_starter_serving_weights_are_synced_on_existing_databases(db):
    from app.models import Food
    from app.seed.loader import seed_all
    f = db.query(Food).filter_by(name="Rajma curry").one()
    f.serving = "1 katori"  # what a database created before this fix contains
    db.commit()
    seed_all(db)
    assert db.query(Food).filter_by(name="Rajma curry").one().serving == "1 katori (150 g)"
