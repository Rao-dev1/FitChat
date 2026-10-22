"""BMI / calorie / protein calculator, the workout and steps allowance, and the Account endpoints."""
import pytest

from app.services import daystats as ds
from app.services import nutrition as nut
from app.services import profile as profile_svc
from app.services import targets as tg
from app.services import weekly as wkly
from app.services import workouts as wk
from app.tools import registry


# ---------- the maths ----------
def test_bmi_and_category():
    s = tg.suggest(weight_kg=70, height_cm=175, age=25, sex="male", activity="light", goal="maintain")
    assert s["bmi"] == 22.9 and s["bmi_category"] == "Healthy range"


def test_mifflin_st_jeor_male_maintenance():
    # 10*70 + 6.25*175 - 5*25 + 5 = 1673.75 ; x1.35 = 2259.6
    s = tg.suggest(weight_kg=70, height_cm=175, age=25, sex="male", activity="light", goal="maintain")
    assert s["bmr"] == 1674 and s["maintenance"] == 2260 and s["calories"] == 2260 and s["protein_g"] == 105


def test_goal_changes_calories_and_protein():
    base = dict(weight_kg=70, height_cm=175, age=25, sex="male", activity="light")
    cut = tg.suggest(**base, goal="fat_loss")
    bulk = tg.suggest(**base, goal="muscle_gain")
    keep = tg.suggest(**base, goal="maintain")
    assert cut["calories"] < keep["calories"] < bulk["calories"]
    assert cut["protein_g"] > bulk["protein_g"] > keep["protein_g"]


def test_everyone_gets_different_numbers():
    a = tg.suggest(weight_kg=55, height_cm=160, age=20, sex="female", activity="sedentary", goal="maintain")
    b = tg.suggest(weight_kg=95, height_cm=185, age=30, sex="male", activity="moderate", goal="maintain")
    assert a["calories"] < 2000 < b["calories"] and a["protein_g"] < b["protein_g"]


def test_calorie_floor_is_applied_and_explained():
    s = tg.suggest(weight_kg=40, height_cm=150, age=60, sex="female", activity="sedentary", goal="fat_loss")
    assert s["calories"] == tg.FLOOR_KCAL["female"] and any("lowest" in n for n in s["notes"])


def test_missing_details_are_listed_not_guessed():
    s = tg.suggest(weight_kg=70, height_cm=None, age=None, sex=None, activity="light", goal="maintain")
    assert not s["ready"] and set(s["missing"]) == {"height", "age", "sex"} and "bmi" not in s


def test_under_18_gets_no_targets():
    s = tg.suggest(weight_kg=60, height_cm=170, age=16, sex="male", activity="light", goal="maintain")
    assert not s["ready"] and "calories" not in s and "bmi_category" not in s
    assert any("adults" in n for n in s["notes"])


@pytest.mark.parametrize("field,bad", [("weight_kg", 10), ("height_cm", 50), ("age", 5), ("age", 150)])
def test_validate_rejects_nonsense(field, bad):
    with pytest.raises(ValueError):
        tg.validate(field, bad)


# ---------- the daily allowance ----------
def test_training_bonus_grows_with_sets_and_is_capped():
    assert tg.training_bonus(5, 70) == 0
    assert tg.training_bonus(6, 70) == 150
    assert tg.training_bonus(16, 70) == 240
    assert tg.training_bonus(60, 70) == 350
    assert tg.training_bonus(16, 90) > tg.training_bonus(16, 60)


def test_steps_bonus_only_above_baseline_and_capped():
    assert tg.steps_bonus(None, 70) == 0 and tg.steps_bonus(3500, 70) == 0
    assert tg.steps_bonus(10000, 70) == 210
    assert tg.steps_bonus(40000, 70) == 300


def test_steps_raise_todays_target(db):
    base = nut.remaining(db)["calorie_target"]
    ds.log_stats(db, steps=10000)
    r = nut.remaining(db)
    assert r["steps_bonus"] > 0 and r["calorie_target"] == base + r["steps_bonus"]
    assert r["base_calorie_target"] == base


def test_workout_and_steps_stack(db):
    base = nut.get_profile(db).calorie_target
    wk.log_workout(db, "Barbell Curl", [{"reps": 10, "weight_kg": 20}] * 8)
    ds.log_stats(db, steps=8000)
    r = nut.remaining(db)
    assert r["training_day_bonus"] > 0 and r["steps_bonus"] > 0
    assert r["calorie_target"] == base + r["training_day_bonus"] + r["steps_bonus"]


def test_weekly_view_includes_steps_allowance(db):
    ds.log_stats(db, steps=10000)
    today = wkly.weekly_summary(db)["days"][-1]
    assert today["calorie_target"] == nut.get_profile(db).calorie_target + tg.steps_bonus(10000, None)


# ---------- saving, applying, automatic mode ----------
BODY = {"weight_kg": 70, "height_cm": 175, "age": 25, "sex": "male", "activity": "light", "goal": "maintain"}


def test_apply_suggested_sets_targets(db):
    profile_svc.save_body(db, dict(BODY))
    v = profile_svc.apply_suggested(db)
    assert v["calorie_target"] == 2260 and v["protein_target_g"] == 105


def test_apply_needs_details(db):
    with pytest.raises(ValueError, match="Add"):
        profile_svc.apply_suggested(db)


def test_automatic_targets_follow_new_weight_readings(db):
    profile_svc.save_body(db, dict(BODY))
    profile_svc.save_body(db, {"auto_targets": True})
    before = nut.get_profile(db).calorie_target
    wkly.log_weight(db, 80.0)
    p = nut.get_profile(db)
    assert p.calorie_target > before and p.protein_target_g == 120


def test_manual_targets_untouched_when_auto_is_off(db):
    profile_svc.save_body(db, dict(BODY))
    p = nut.get_profile(db)
    p.calorie_target = 2750
    db.commit()
    wkly.log_weight(db, 80.0)
    assert nut.get_profile(db).calorie_target == 2750


def test_saving_weight_also_records_a_reading(db):
    profile_svc.save_body(db, {"weight_kg": 68.5})
    assert wkly.weight_series(db)[-1]["weight_kg"] == 68.5


def test_bad_body_values_rejected(db):
    with pytest.raises(ValueError):
        profile_svc.save_body(db, {"height_cm": 20})
    with pytest.raises(ValueError):
        profile_svc.save_body(db, {"sex": "robot"})


# ---------- HTTP + coach ----------
def test_profile_endpoints(client):
    r = client.get("/api/profile")
    assert r.status_code == 200 and r.json()["suggestion"]["ready"] is False
    r = client.put("/api/profile", json=BODY)
    assert r.status_code == 200 and r.json()["suggestion"]["calories"] == 2260
    assert client.post("/api/profile/apply-suggested").json()["calorie_target"] == 2260
    assert client.put("/api/profile", json={"height_cm": 30}).status_code == 422
    assert client.put("/api/profile", json={"sex": "x"}).status_code == 422


def test_summary_reports_steps_allowance(client):
    client.post("/api/daystats", json={"steps": 9000})
    r = client.get("/api/summary/today").json()["remaining"]
    assert r["steps_bonus"] > 0 and r["steps"] == 9000


def test_coach_can_set_body_details_and_recalculate(db):
    out, _ = registry.execute(db, "update_profile", {**{k: v for k, v in BODY.items() if k != "goal"}, "recalculate": True})
    assert out["calorie_target"] == 2260 and out["suggestion"]["ready"] and out["height_cm"] == 175
