from datetime import date, timedelta

import pytest

from app.llm.fake import ScriptedLLM, call, say
from app.models import MealLog, WorkoutSession, WorkoutSet
from app.services import nutrition as nut
from app.services import weekly
from app.services import workouts as wk


def meal(db, day, kcal, protein):
    db.add(MealLog(day=day, food_name="x", calories=kcal, protein_g=protein))
    db.commit()


def sets(db, day, n, reps=10, w=40):
    s = WorkoutSession(day=day)
    ex = wk.find_exercise(db, "Barbell Bench Press - Medium Grip")
    s.sets = [WorkoutSet(exercise_id=ex.id, set_number=i + 1, reps=reps, weight_kg=w) for i in range(n)]
    db.add(s)
    db.commit()


def test_empty_week(db):
    r = weekly.weekly_summary(db)
    assert len(r["days"]) == 7 and r["totals"]["days_logged"] == 0 and r["totals"]["avg_calories"] is None
    assert r["lines"] == ["No food logged in this period yet."] and r["weight"]["latest"] is None


def test_averages_count_only_logged_days_and_protein_hits(db):
    p = nut.get_profile(db)
    p.calorie_target, p.protein_target_g = 2000, 100
    db.commit()
    t = date.today()
    meal(db, t, 1800, 95)                     # hits (>= 90)
    meal(db, t - timedelta(days=1), 2400, 60)  # over, misses
    r = weekly.weekly_summary(db)["totals"]
    assert r["days_logged"] == 2 and r["avg_calories"] == 2100 and r["avg_protein_g"] == 77.5
    assert r["protein_hit_days"] == 1 and r["over_calorie_days"] == 1


def test_training_day_raises_that_days_target_and_counts_sets(db):
    t = date.today()
    sets(db, t, 6)
    sets(db, t - timedelta(days=2), 3)  # a short session: not a training day
    r = weekly.weekly_summary(db)
    today = r["days"][-1]
    assert today["trained"] and today["calorie_target"] == nut.get_profile(db).calorie_target + nut.TRAINING_DAY_CALORIE_BONUS
    assert r["totals"]["training_days"] == 1 and r["totals"]["workout_days"] == 2 and r["totals"]["total_sets"] == 9
    assert today["volume_kg"] == 6 * 400


def test_window_excludes_older_days(db):
    meal(db, date.today() - timedelta(days=8), 3000, 10)
    assert weekly.weekly_summary(db)["totals"]["days_logged"] == 0
    assert weekly.weekly_summary(db, days=10)["totals"]["days_logged"] == 1


def test_weight_upsert_validation_and_profile_sync(client, db):
    assert client.post("/api/weight", json={"weight_kg": 102.34}).status_code == 201
    assert client.post("/api/weight", json={"weight_kg": 101.8}).status_code == 201  # same day replaces
    ws = client.get("/api/weight").json()
    assert ws == [{"day": date.today().isoformat(), "weight_kg": 101.8}]
    assert client.get("/api/profile").json()["weight_kg"] == 101.8
    for bad in (0, 10, 500, -5):
        assert client.post("/api/weight", json={"weight_kg": bad}).status_code == 422
    fut = (date.today() + timedelta(days=1)).isoformat()
    assert client.post("/api/weight", json={"weight_kg": 90, "day": fut}).status_code == 422
    assert len(client.get("/api/weight").json()) == 1


def test_weight_trend_and_delete(client, db):
    t = date.today()
    for back, kg in ((14, 104.0), (7, 103.0), (0, 102.0)):
        client.post("/api/weight", json={"weight_kg": kg, "day": (t - timedelta(days=back)).isoformat()})
    w = client.get("/api/week?days=7").json()["weight"]
    assert w["latest"]["weight_kg"] == 102.0 and w["change_kg"] == -2.0 and w["span_days"] == 14
    assert w["per_week_kg"] == -1.0
    assert client.delete(f"/api/weight/{t.isoformat()}").status_code == 204
    assert client.delete(f"/api/weight/{t.isoformat()}").status_code == 404
    assert client.get("/api/profile").json()["weight_kg"] == 103.0  # falls back to the latest remaining


def test_week_endpoint_shape_and_bad_days(client, db):
    j = client.get("/api/week").json()
    assert {"days", "totals", "weight", "lines", "summary", "weights"} <= set(j)
    assert client.get("/api/week?days=0").status_code == 422 and client.get("/api/week?days=500").status_code == 422


def test_coach_tools_weekly_summary_and_log_weight(client, db):
    meal(db, date.today(), 1500, 100)
    client.set_llm(ScriptedLLM([call("log_weight", weight_kg=101.5), call("get_weekly_summary"), say("done")]))
    r = client.post("/api/chat", json={"message": "I weigh 101.5, how was my week?"})
    assert r.status_code == 200
    assert client.get("/api/weight").json()[0]["weight_kg"] == 101.5
