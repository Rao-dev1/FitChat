from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.llm.fake import ScriptedLLM, call, say
from app.models import Exercise, Routine, WorkoutSession, WorkoutSet
from app.services import routines as rt
from app.services import workouts as wk

BENCH = "Barbell Bench Press - Medium Grip"


def eid(db, name):
    return wk.find_exercise(db, name).id


def make(client, name="Push A", items=None):
    items = items or [{"name": BENCH, "sets": 3, "rep_min": 6, "rep_max": 10, "rest_s": 120},
                      {"name": "Triceps Pushdown", "sets": 3}]
    return client.post("/api/routines", json={"name": name, "exercises": items})


def log(db, name, day, n=3, reps=8, w=40):
    s = db.scalar(select(WorkoutSession).where(WorkoutSession.day == day)) or WorkoutSession(day=day)
    db.add(s)
    db.flush()
    for i in range(n):
        db.add(WorkoutSet(session_id=s.id, exercise_id=eid(db, name), set_number=i + 1, reps=reps, weight_kg=w))
    db.commit()


def test_every_template_exercise_exists_and_is_strength(db):
    for key, (_n, _d, rows) in rt.TEMPLATES.items():
        for ex, sets, lo, hi, rest in rows:
            e = wk.find_exercise(db, ex, "strength")
            assert e is not None and e.name == ex, f"{key}: {ex}"
            assert 1 <= sets <= 10 and 1 <= lo <= hi and 15 <= rest <= 600


def test_create_list_update_delete(client, db):
    r = make(client)
    assert r.status_code == 201
    j = r.json()
    assert [e["name"] for e in j["exercises"]] == [BENCH, "Triceps Pushdown"] and j["total_sets"] == 6
    assert j["exercises"][0]["rest_s"] == 120 and j["exercises"][1]["rest_s"] == 90
    lst = client.get("/api/routines").json()
    assert len(lst["routines"]) == 1 and {t["key"] for t in lst["templates"]} == set(rt.TEMPLATES)
    up = client.put(f"/api/routines/{j['id']}", json={"name": "Push B", "exercises": [{"name": BENCH, "sets": 5}]})
    assert up.status_code == 200 and up.json()["name"] == "Push B" and len(up.json()["exercises"]) == 1
    assert db.query(rt.RoutineExercise).count() == 1  # old lines replaced, not piled up
    assert client.delete(f"/api/routines/{j['id']}").status_code == 204
    assert client.delete(f"/api/routines/{j['id']}").status_code == 404
    assert db.query(rt.RoutineExercise).count() == 0 and client.put("/api/routines/9", json={"name": "x", "exercises": [{"name": BENCH}]}).status_code == 404


@pytest.mark.parametrize("body,code", [
    ({"name": "", "exercises": [{"name": BENCH}]}, 422),
    ({"name": "X", "exercises": []}, 422),
    ({"name": "X", "exercises": [{"name": "nonexistent lift zzz"}]}, 422),
    ({"name": "X", "exercises": [{"name": BENCH, "sets": 0}]}, 422),
    ({"name": "X", "exercises": [{"name": BENCH, "rep_min": 12, "rep_max": 8}]}, 422),
    ({"name": "X", "exercises": [{"name": BENCH, "rest_s": 5}]}, 422),
    ({"name": "X", "exercises": [{"name": BENCH}, {"name": BENCH}]}, 422),
])
def test_bad_routines_rejected_and_nothing_saved(client, db, body, code):
    assert client.post("/api/routines", json=body).status_code == code
    assert db.query(Routine).count() == 0


def test_duplicate_name_blocked_case_insensitive_but_rename_to_self_ok(client):
    first = make(client, "Push A").json()
    assert make(client, "push a").status_code == 409
    assert client.put(f"/api/routines/{first['id']}", json={"name": "PUSH A", "exercises": [{"name": BENCH}]}).status_code == 200


def test_failed_update_leaves_routine_unchanged(client, db):
    j = make(client).json()
    bad = client.put(f"/api/routines/{j['id']}", json={"name": "Push A", "exercises": [{"name": BENCH}, {"name": "zzz nothing"}]})
    assert bad.status_code == 422
    assert len(client.get("/api/routines").json()["routines"][0]["exercises"]) == 2


def test_from_template_and_repeat_gets_new_name(client):
    a = client.post("/api/routines/from-template", json={"key": "push"})
    b = client.post("/api/routines/from-template", json={"key": "push"})
    assert a.status_code == b.status_code == 201 and a.json()["name"] == "Push day" and b.json()["name"] == "Push day 2"
    assert len(a.json()["exercises"]) == 6
    assert client.post("/api/routines/from-template", json={"key": "nope"}).status_code == 422


def test_suggestion_picks_longest_untrained_routine(client, db):
    push = make(client, "Push", [{"name": BENCH}, {"name": "Triceps Pushdown"}]).json()
    pull = make(client, "Pull", [{"name": "Wide-Grip Lat Pulldown"}, {"name": "Barbell Curl"}]).json()
    assert client.get("/api/routines").json()["suggestion"]["name"] == "Push"  # nothing trained: first made
    log(db, BENCH, date.today() - timedelta(days=2)); log(db, "Triceps Pushdown", date.today() - timedelta(days=2))
    s = client.get("/api/routines").json()["suggestion"]
    assert s["name"] == "Pull" and s["reason"] == "Not trained yet."
    log(db, "Wide-Grip Lat Pulldown", date.today() - timedelta(days=5)); log(db, "Barbell Curl", date.today() - timedelta(days=5))
    s = client.get("/api/routines").json()["suggestion"]
    assert s["name"] == "Pull" and "5 days" in s["reason"]
    rs = {r["name"]: r for r in client.get("/api/routines").json()["routines"]}
    assert rs["Push"]["days_since"] == 2 and rs["Pull"]["days_since"] == 5


def test_one_exercise_of_many_does_not_count_as_training_the_routine(client, db):
    make(client, "Big", [{"name": BENCH}, {"name": "Triceps Pushdown"}, {"name": "Side Lateral Raise"}, {"name": "Dumbbell Shoulder Press"}])
    log(db, BENCH, date.today() - timedelta(days=1))  # 1 of 4 is under half
    assert client.get("/api/routines").json()["routines"][0]["last_done"] is None


def test_trained_today_leaves_no_suggestion(client, db):
    make(client, "Solo", [{"name": BENCH}])
    log(db, BENCH, date.today())
    s = client.get("/api/routines").json()["suggestion"]
    assert s["routine_id"] is None and "already trained" in s["reason"]


def test_plan_shows_last_time_progress_and_flags_busy_gear(client, db):
    j = make(client, "Push", [{"name": BENCH, "sets": 3}, {"name": "Triceps Pushdown", "sets": 3}]).json()
    log(db, BENCH, date.today() - timedelta(days=3), n=3, reps=10, w=60)
    log(db, BENCH, date.today(), n=2, reps=8, w=62.5)
    p = client.get(f"/api/routines/{j['id']}/plan").json()
    bench, tri = p["exercises"]
    assert bench["sets_done"] == 2 and bench["last_time"]["sets"] and bench["blocked"] is None
    assert p["target_sets"] == 6 and p["done_sets"] == 2 and p["complete"] is False
    client.put("/api/equipment/unavailable", json={"items": ["barbell"]})
    p = client.get(f"/api/routines/{j['id']}/plan").json()
    b = p["exercises"][0]
    assert "barbell" in b["blocked"] and 1 <= len(b["alternatives"]) <= 3
    assert all(a["exercise_id"] != b["exercise_id"] for a in b["alternatives"])
    assert p["exercises"][1]["blocked"] is None
    assert client.get("/api/routines/999/plan").status_code == 404


def test_plan_flags_injury(client, db):
    j = make(client, "Push", [{"name": "Dumbbell Shoulder Press"}]).json()
    client.post("/api/injuries", json={"area": "shoulder", "severity": "moderate"})
    assert "shoulder" in client.get(f"/api/routines/{j['id']}/plan").json()["exercises"][0]["blocked"]


def test_complete_when_all_sets_done(client, db):
    j = make(client, "Tiny", [{"name": BENCH, "sets": 2}]).json()
    log(db, BENCH, date.today(), n=2)
    assert client.get(f"/api/routines/{j['id']}/plan").json()["complete"] is True


def test_coach_tools(client, db):
    client.set_llm(ScriptedLLM([
        call("create_routine", name="Coach push", exercises=[{"name": BENCH, "sets": 4, "rep_min": 6, "rep_max": 8, "rest_s": 150}]),
        call("list_routines"), call("get_routine_plan", name="coach"), say("ok")]))
    assert client.post("/api/chat", json={"message": "make me a push day"}).status_code == 200
    rs = client.get("/api/routines").json()["routines"]
    assert len(rs) == 1 and rs[0]["exercises"][0]["rest_s"] == 150
    client.set_llm(ScriptedLLM([call("create_routine", name="Bad", exercises=[{"name": "zzz nothing"}]), say("ok")]))
    client.post("/api/chat", json={"message": "x"})
    assert len(client.get("/api/routines").json()["routines"]) == 1
