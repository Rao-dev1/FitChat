from datetime import date, datetime, timedelta

import pytest

from app.models import MealLog, WaterLog, WeightLog, WorkoutSession, WorkoutSet
from app.services import arc, nudges
from app.services import nutrition as nut
from app.services import workouts as wk

D0 = arc.ARC_START


def eat(db, day, protein=100, cal=2000):
    db.add(MealLog(day=day, food_name="x", quantity=1, calories=cal, protein_g=protein))
    db.commit()


def drink(db, day, ml=3000):
    db.add(WaterLog(day=day, ml=ml))
    db.commit()


def train(db, day, sets=6):
    s = WorkoutSession(day=day)
    db.add(s)
    db.flush()
    ex = wk.find_exercise(db, "Barbell Bench Press - Medium Grip")
    for i in range(sets):
        db.add(WorkoutSet(session_id=s.id, exercise_id=ex.id, set_number=i + 1, reps=8, weight_kg=40))
    db.commit()


# ---- sleep and steps
def test_daystats_merge_validate_series(client):
    assert client.post("/api/daystats", json={"sleep_h": 7.5}).status_code == 200
    client.post("/api/daystats", json={"steps": 8200})
    r = client.get("/api/daystats?days=7").json()
    assert r["today"] == {"day": date.today().isoformat(), "sleep_h": 7.5, "steps": 8200}
    assert r["avg_sleep_h"] == 7.5 and r["avg_steps"] == 8200
    for bad in ({}, {"sleep_h": 0}, {"sleep_h": 30}, {"steps": -1}, {"steps": 500000},
                {"sleep_h": 7, "day": (date.today() + timedelta(days=1)).isoformat()}):
        assert client.post("/api/daystats", json=bad).status_code == 422
    assert client.delete(f"/api/daystats/{date.today().isoformat()}").status_code == 200
    assert client.delete(f"/api/daystats/{date.today().isoformat()}").status_code == 404


def test_low_sleep_noted(client):
    client.post("/api/daystats", json={"sleep_h": 5.5})
    assert "under 7 h" in client.get("/api/daystats").json()["summary"]


# ---- arc
def test_arc_before_and_after(db):
    assert arc.status(db, D0 - timedelta(days=3))["phase"] == "before"
    a = arc.status(db, arc.ARC_END + timedelta(days=5))
    assert a["phase"] == "finished" and a["day_number"] == 92 and a["days_left"] == 0


def test_arc_day_count_and_dots(db):
    a = arc.status(db, D0 + timedelta(days=13))
    assert a["day_number"] == 14 and a["total_days"] == 92 and a["days_left"] == 78
    assert len(a["dots"]) == 92 and a["dots"][13]["today"] and a["dots"][14]["state"] == "future"
    assert a["dots"][0]["state"] == "missed"


def test_streaks_today_pending_does_not_break(db):
    today = D0 + timedelta(days=5)
    for i in range(1, 4):  # three days ending yesterday
        d = today - timedelta(days=i)
        eat(db, d, protein=100)
        drink(db, d)
    a = arc.status(db, today)
    assert a["streaks"]["protein_days"] == 3 and a["streaks"]["water_days"] == 3 and a["streaks"]["logging_days"] == 3
    eat(db, today, protein=100)
    assert arc.status(db, today)["streaks"]["protein_days"] == 4


def test_streak_breaks_on_low_protein(db):
    today = D0 + timedelta(days=5)
    eat(db, today, 100); eat(db, today - timedelta(days=1), 20); eat(db, today - timedelta(days=2), 100)
    a = arc.status(db, today)
    assert a["streaks"]["protein_days"] == 1 and a["streaks"]["logging_days"] == 3
    assert [d["state"] for d in a["dots"][3:6]] == ["full", "logged", "full"]


def test_gym_week_and_weeks_streak(db):
    nut.get_profile(db).gym_days_goal = 2
    db.commit()
    mon = D0 + timedelta(days=(7 - D0.weekday()) % 7)  # first Monday in the arc
    train(db, mon); train(db, mon + timedelta(days=2))               # week 1: 2 of 2
    train(db, mon + timedelta(days=7)); train(db, mon + timedelta(days=9))  # week 2: 2 of 2
    today = mon + timedelta(days=14)                                 # Monday of week 3
    train(db, today)
    a = arc.status(db, today)
    assert a["gym_week"] == {"trained": 1, "goal": 2} and a["streaks"]["gym_weeks"] == 2
    train(db, today + timedelta(days=1))
    assert arc.status(db, today + timedelta(days=1))["streaks"]["gym_weeks"] == 3


def test_light_session_is_not_a_gym_day(db):
    train(db, D0, sets=3)
    assert arc.status(db, D0)["gym_week"]["trained"] == 0


def test_weight_projection_needs_trend(db):
    today = D0 + timedelta(days=20)
    db.add(WeightLog(day=D0, weight_kg=102)); db.commit()
    assert "projected_end_kg" not in arc.status(db, today)["weight"]
    for i, w in ((8, 101.2), (14, 100.4), (20, 99.6)):
        db.add(WeightLog(day=D0 + timedelta(days=i), weight_kg=w))
    db.commit()
    w = arc.status(db, today)["weight"]
    assert w["change_kg"] == -2.4 and w["per_week_kg"] < 0
    assert w["projected_end_kg"] < w["latest_kg"]
    assert "estimate" in arc.status(db, today)["summary"]


def test_arc_endpoint(client):
    r = client.get("/api/arc").json()
    assert {"phase", "streaks", "dots", "gym_week", "weight", "summary"} <= set(r)


# ---- nudges
def at(h, day=None):
    return datetime.combine(day or date.today(), datetime.min.time()).replace(hour=h)


def kinds(db, h):
    return [n["kind"] for n in nudges.compute(db, at(h))]


def test_morning_nudges_quiet(db):
    k = kinds(db, 9)
    assert "food" not in k and "water" not in k and "protein" not in k and "sleep" in k


def test_food_nudge_after_11_clears_when_logged(db):
    assert "food" in kinds(db, 12)
    eat(db, date.today())
    assert "food" not in kinds(db, 12)


def test_water_behind_nudge(db):
    assert "water" in kinds(db, 15)
    drink(db, date.today(), 2800)
    assert "water" not in kinds(db, 15)


def test_protein_nudge_evening(db):
    eat(db, date.today(), protein=30, cal=800)
    assert "protein" in kinds(db, 19) and "protein" not in kinds(db, 15)


def test_gym_nudge_only_with_routine_and_not_trained(db, client):
    assert "gym" not in kinds(db, 17)
    client.post("/api/routines/from-template", json={"key": "push"})
    assert "gym" in kinds(db, 17) and "gym" not in kinds(db, 10)
    train(db, date.today())
    assert "gym" not in kinds(db, 17)


def test_weekly_nudges_and_cap(db):
    k = kinds(db, 21)
    assert "weight" in k and len(k) <= nudges.MAX_NUDGES
    db.add(WeightLog(day=date.today(), weight_kg=100)); db.commit()
    assert "weight" not in kinds(db, 21)


def test_nudges_endpoint(client):
    r = client.get("/api/nudges").json()
    assert isinstance(r["nudges"], list) and "kinds" in r
    for n in r["nudges"]:
        assert {"kind", "text", "action"} <= set(n)
