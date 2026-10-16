from datetime import date, timedelta

import pytest

from app.llm.fake import ScriptedLLM, call, say
from app.models import WorkoutSession, WorkoutSet
from app.services import progress as prog
from app.services import workouts as wk

BENCH = "Barbell Bench Press - Medium Grip"


def ex_id(db, name=BENCH):
    return wk.find_exercise(db, name).id


def post(client, eid, *sets):
    return client.post("/api/workout/sets", json={"exercise_id": eid, "sets": [{"reps": r, "weight_kg": w} for r, w in sets]})


def test_e1rm_math():
    assert prog.e1rm(100, 1) == 100 and prog.e1rm(60, 10) == 80.0 and prog.e1rm(0, 12) == 0.0


def test_log_sets_via_api_groups_today_and_returns_remaining(client, db):
    eid = ex_id(db)
    r = post(client, eid, (10, 40), (8, 45))
    assert r.status_code == 201
    body = r.json()
    assert body["sets_logged"] == 2 and body["prs"] == []
    g = body["today"]["exercises"][0]
    assert g["name"] == BENCH and [(s["set_number"], s["reps"], s["weight_kg"]) for s in g["sets"]] == [(1, 10, 40), (2, 8, 45)]
    assert g["volume_kg"] == 10 * 40 + 8 * 45 and body["today"]["total_sets"] == 2
    assert client.get("/api/workout/today").json()["total_sets"] == 2
    assert post(client, eid, (8, 45)).json()["today"]["exercises"][0]["sets"][-1]["set_number"] == 3  # numbering continues


@pytest.mark.parametrize("reps,w", [(0, 40), (101, 40), (5, -1), (5, 600)])
def test_bad_sets_are_rejected_and_nothing_is_stored(client, db, reps, w):
    assert post(client, ex_id(db), (reps, w)).status_code == 422
    assert db.query(WorkoutSet).count() == 0


def test_unknown_exercise_and_empty_sets(client, db):
    assert post(client, "nope", (5, 5)).status_code == 404
    assert client.post("/api/workout/sets", json={"exercise_id": ex_id(db), "sets": []}).status_code == 422


def test_delete_set_renumbers_and_removes_empty_session(client, db):
    eid = ex_id(db)
    ids = [s["id"] for s in post(client, eid, (10, 40), (9, 40), (8, 40)).json()["today"]["exercises"][0]["sets"]]
    after = client.delete(f"/api/workout/sets/{ids[0]}").json()["today"]["exercises"][0]["sets"]
    assert [(s["set_number"], s["reps"]) for s in after] == [(1, 9), (2, 8)]
    client.delete(f"/api/workout/sets/{ids[1]}")
    client.delete(f"/api/workout/sets/{ids[2]}")
    assert db.query(WorkoutSession).count() == 0
    assert client.delete(f"/api/workout/sets/{ids[0]}").status_code == 404


def test_six_sets_turn_on_the_training_day_calorie_bonus(client, db):
    eid = ex_id(db)
    r = post(client, eid, *[(10, 40)] * 6).json()
    assert r["today"]["trained_today"] and r["remaining"]["training_day_bonus"] == 150


# ---- personal bests ------------------------------------------------------------------------------------------
def test_first_time_is_not_a_pr_but_a_heavier_later_set_is(db):
    eid = ex_id(db)
    d1, d2 = date.today() - timedelta(days=7), date.today()
    assert wk.log_sets(db, eid, [{"reps": 10, "weight_kg": 40}], day=d1)["prs"] == []
    r = wk.log_sets(db, eid, [{"reps": 10, "weight_kg": 40}, {"reps": 8, "weight_kg": 50}], day=d2)
    assert r["prs"] and r["prs"][0]["kind"] == "e1rm" and r["prs"][0]["value"] == 63.3
    assert "New best estimated 1-rep max" in r["prs"][0]["text"]
    assert wk.log_sets(db, eid, [{"reps": 5, "weight_kg": 30}], day=d2)["prs"] == []


def test_bodyweight_pr_uses_reps(db):
    eid = wk.find_exercise(db, "Pushups").id
    wk.log_sets(db, eid, [{"reps": 15}], day=date.today() - timedelta(days=3))
    assert wk.log_sets(db, eid, [{"reps": 18}])["prs"][0]["kind"] == "reps"


# ---- last time + next hint -----------------------------------------------------------------------------------
def seed(db, eid, days_ago, sets):
    wk.log_sets(db, eid, [{"reps": r, "weight_kg": w} for r, w in sets], day=date.today() - timedelta(days=days_ago))


def test_last_time_excludes_today_and_hint_adds_weight_when_top_of_range_reached(db):
    eid = ex_id(db)
    hi = prog._rep_range(wk.get_profile(db).goal)[1]
    seed(db, eid, 6, [(hi, 40)] * 3)
    wk.log_sets(db, eid, [{"reps": 5, "weight_kg": 99}])  # today must not count as "last time"
    last = prog.last_performance(db, eid)
    assert last["sets"] == [{"reps": hi, "weight_kg": 40.0}] * 3 and last["next_weight_kg"] == 42.5
    assert "42.5" in last["next_hint"]


def test_hint_stays_and_adds_reps_otherwise(db):
    eid = ex_id(db)
    lo, hi = prog._rep_range(wk.get_profile(db).goal)
    seed(db, eid, 5, [(lo + 1, 40), (lo + 1, 40)])
    h = prog.last_performance(db, eid)
    assert h["next_weight_kg"] == 40 and "one more rep" in h["next_hint"]
    seed(db, eid, 2, [(lo - 2, 50), (lo, 50)])
    assert "until every set reaches" in prog.last_performance(db, eid)["next_hint"]


def test_progress_endpoint_has_history_bests_and_last(client, db):
    eid = ex_id(db)
    seed(db, eid, 14, [(10, 40), (8, 45)])
    seed(db, eid, 7, [(10, 45), (8, 50)])
    post(client, eid, (6, 50))
    p = client.get(f"/api/workout/progress/{eid}").json()
    assert p["sessions_logged"] == 3 and [h["day"] for h in p["history"]] == sorted([h["day"] for h in p["history"]], reverse=True)
    assert p["personal_bests"]["e1rm"]["weight_kg"] == 50 and p["personal_bests"]["heaviest"]["weight_kg"] == 50
    assert p["today"][0]["reps"] == 6 and p["last"]["day"] == (date.today() - timedelta(days=7)).isoformat()
    assert client.get("/api/workout/progress/nope").status_code == 404


def test_history_lists_exercises_most_recent_first(client, db):
    seed(db, ex_id(db), 9, [(10, 40)])
    seed(db, wk.find_exercise(db, "Barbell Curl").id, 2, [(12, 20)])
    names = [h["name"] for h in client.get("/api/workout/history").json()]
    assert names[0] == "Barbell Curl" and BENCH in names


# ---- coach integration ---------------------------------------------------------------------------------------
def test_exercise_options_carry_last_time_for_exercises_with_history(db):
    eid = ex_id(db)
    seed(db, eid, 4, [(10, 40)] * 3)
    opts = wk.exercise_options(db, "chest", limit=100)["options"]
    mine = [o for o in opts if o["id"] == eid]
    assert mine and mine[0]["last_time"]["sets"][0]["weight_kg"] == 40.0
    assert all("last_time" not in o for o in opts if o["id"] != eid)


def test_coach_progress_tool_and_pr_reporting(client, db):
    eid = ex_id(db)
    seed(db, eid, 5, [(10, 40)])
    llm = ScriptedLLM([call("log_workout", exercise=BENCH, sets=[{"reps": 8, "weight_kg": 50}]),
                       call("get_exercise_progress", name="bench press"), say("Nice.")])
    client.set_llm(llm)
    client.post("/api/chat", json={"message": "did 8 at 50 on bench"})
    logged = llm.calls[1][-1].tool_results[0].result
    assert logged["logged"] and logged["prs"] and "text" in logged["prs"][0]
    shown = llm.calls[2][-1].tool_results[0].result
    assert shown["found"] and shown["personal_bests"]["e1rm"]["weight_kg"] == 50 and shown["sessions_logged"] == 2


def test_coach_log_workout_rejects_absurd_numbers_without_storing(client, db):
    client.set_llm(ScriptedLLM([call("log_workout", exercise=BENCH, sets=[{"reps": 8, "weight_kg": 5000}]), say("x")]))
    client.post("/api/chat", json={"message": "x"})
    assert db.query(WorkoutSet).count() == 0
