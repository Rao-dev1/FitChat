"""Accounts: two people must never see or change each other's data, however the data is reached."""
import os

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import accounts, auth
from app.db import Base, get_db, make_engine, open_session
from app.deps import get_llm
from app.main import app
from app.models import Food, MealLog, Profile, SiteSetting
from app.seed.loader import seed_exercises, seed_user
from app.tenancy import key_get
from app.llm.fake import ScriptedLLM


@pytest.fixture()
def world():
    url = os.environ.get("TEST_DATABASE_URL")  # set to run these against a real Postgres
    if url:
        engine = make_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with maker() as s:
        seed_exercises(s)
    yield engine, maker
    for db in _opened:  # release locks so the next test can drop the tables (matters on Postgres)
        db.close()
    _opened.clear()
    engine.dispose()


_opened: list = []


def user_db(maker, uid, seed=True):
    db = open_session(uid, maker)
    _opened.append(db)
    if seed:
        seed_user(db)
    return db


@pytest.fixture()
def two(world):
    engine, maker = world
    return user_db(maker, "alice"), user_db(maker, "bob")


def test_each_user_gets_their_own_starter_data(two):
    a, b = two
    na = len(a.scalars(select(Food)).all())
    assert na > 20 and na == len(b.scalars(select(Food)).all())
    assert {f.user_id for f in a.scalars(select(Food))} == {"alice"}
    assert a.scalar(select(Profile)).user_id == "alice"


def test_rows_are_invisible_to_the_other_user(two):
    a, b = two
    a.add(MealLog(food_name="Alice secret", calories=500, protein_g=30)); a.commit()
    assert [m.food_name for m in a.scalars(select(MealLog))] == ["Alice secret"]
    assert b.scalars(select(MealLog)).all() == []
    mid = a.scalar(select(MealLog)).id
    assert b.get(MealLog, mid) is None  # even by primary key


def test_bulk_update_and_delete_only_touch_own_rows(two):
    a, b = two
    for db, n in ((a, "A meal"), (b, "B meal")):
        db.add(MealLog(food_name=n, calories=1, protein_g=1)); db.commit()
    b.query(MealLog).delete(); b.commit()
    assert [m.food_name for m in a.scalars(select(MealLog))] == ["A meal"]
    assert b.scalars(select(MealLog)).all() == []


def test_composite_key_tables_do_not_collide(two):
    from datetime import date
    from app.services import weekly
    a, b = two
    d = date(2026, 10, 1)
    weekly.log_weight(a, 80, d); weekly.log_weight(b, 95, d)
    assert key_get(a, __import__("app.models", fromlist=["WeightLog"]).WeightLog, day=d).weight_kg == 80
    assert key_get(b, __import__("app.models", fromlist=["WeightLog"]).WeightLog, day=d).weight_kg == 95
    assert weekly.delete_weight(a, d) is True
    assert key_get(b, __import__("app.models", fromlist=["WeightLog"]).WeightLog, day=d).weight_kg == 95


def test_relationship_loads_stay_scoped(two):
    from app.services import workouts as wk
    a, b = two
    ex = a.scalar(select(__import__("app.models", fromlist=["Exercise"]).Exercise).limit(1))
    wk.log_sets(a, ex.id, [{"reps": 5, "weight_kg": 20}])
    sess = a.scalar(select(__import__("app.models", fromlist=["WorkoutSession"]).WorkoutSession))
    assert len(sess.sets) == 1
    assert b.scalars(select(__import__("app.models", fromlist=["WorkoutSet"]).WorkoutSet)).all() == []


def test_a_session_without_a_user_sees_and_writes_nothing(world):
    engine, maker = world
    alice = user_db(maker, "alice")
    nobody = open_session(None, maker); _opened.append(nobody)
    assert nobody.scalars(select(Food)).all() == []
    nobody.add(MealLog(food_name="x", calories=1, protein_g=1))
    with pytest.raises(RuntimeError):
        nobody.commit()
    assert alice.scalars(select(MealLog)).all() == []


def test_cannot_write_a_row_for_someone_else(two):
    a, b = two
    a.add(MealLog(user_id="bob", food_name="sneaky", calories=1, protein_g=1))
    with pytest.raises(RuntimeError):
        a.commit()


# ---------- through the real HTTP layer ----------
@pytest.fixture()
def api(world):
    engine, maker = world

    def fake_get_db(request: Request):
        db = open_session(request.headers["x-test-user"], maker)
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[get_llm] = lambda: ScriptedLLM([])
    c = TestClient(app)
    for uid in ("alice", "bob"):
        with maker() as s:
            s.info["uid"] = uid
            seed_user(s)
    yield c
    app.dependency_overrides.clear()


def h(uid):
    return {"x-test-user": uid}


def test_http_meals_and_foods_are_separate(api):
    r = api.post("/api/meals", json={"name": "Paneer", "quantity": 1}, headers=h("alice"))
    assert r.status_code == 201, r.text
    assert api.get("/api/summary/today", headers=h("alice")).json()["totals"]["calories"] > 0
    assert api.get("/api/summary/today", headers=h("bob")).json()["totals"]["calories"] == 0


def test_http_cannot_edit_or_delete_another_users_food(api):
    mine = api.post("/api/foods", json={"name": "Alice shake", "serving": "1 glass", "calories": 300,
                                        "protein_g": 30}, headers=h("alice"))
    assert mine.status_code == 201, mine.text
    fid = mine.json()["id"]
    assert api.delete(f"/api/foods/{fid}", headers=h("bob")).status_code == 404
    names_b = [f["name"] for f in api.get("/api/foods", headers=h("bob")).json()]
    assert "Alice shake" not in names_b
    assert api.delete(f"/api/foods/{fid}", headers=h("alice")).status_code == 204


def test_same_name_allowed_for_different_users(api):
    body = {"name": "Mom's dal", "serving": "1 bowl", "calories": 200, "protein_g": 10}
    assert api.post("/api/foods", json=body, headers=h("alice")).status_code == 201
    assert api.post("/api/foods", json=body, headers=h("bob")).status_code == 201


def test_chat_history_is_private(api):
    api.app.dependency_overrides[get_llm] = lambda: ScriptedLLM([])
    from app.models import ChatMessage
    # write directly, then read back through the API as each user
    maker = next(iter(api.app.dependency_overrides[get_db].__closure__)).cell_contents  # the sessionmaker
    with maker() as s:
        s.info["uid"] = "alice"; s.add(ChatMessage(role="user", content="alice only")); s.commit()
    assert [m["content"] for m in api.get("/api/chat/history", headers=h("alice")).json()] == ["alice only"]
    assert api.get("/api/chat/history", headers=h("bob")).json() == []


def test_export_and_delete_my_data(api):
    api.post("/api/meals", json={"name": "Paneer", "quantity": 1}, headers=h("alice"))
    api.post("/api/meals", json={"name": "Paneer", "quantity": 2}, headers=h("bob"))
    out = api.get("/api/export", headers=h("alice")).json()
    assert len(out["tables"]["meal_logs"]) == 1 and "user_secrets" not in out["tables"]
    assert all("user_id" not in r for r in out["tables"]["meal_logs"])
    assert api.post("/api/me/delete-data", json={"confirm": "nope"}, headers=h("alice")).status_code == 422
    assert api.post("/api/me/delete-data", json={"confirm": "DELETE"}, headers=h("alice")).status_code == 200
    assert api.get("/api/export", headers=h("alice")).json()["tables"]["meal_logs"] == []
    assert len(api.get("/api/export", headers=h("bob")).json()["tables"]["meal_logs"]) == 1


def _seed_rich_data(api_client, uid):
    """Log a bit of everything that has links between tables."""
    H = h(uid)
    api_client.post("/api/meals", json={"name": "Paneer", "quantity": 2}, headers=H)
    api_client.post("/api/weight", json={"weight_kg": 91.5}, headers=H)
    api_client.post("/api/daystats", json={"sleep_h": 7.5, "steps": 8000}, headers=H)
    api_client.post("/api/foods", json={"name": "My shake", "serving": "1 glass", "calories": 300, "protein_g": 30}, headers=H)
    ex = api_client.get("/api/exercises?q=bench", headers=H).json()
    return ex


def test_restore_moves_everything_to_another_account_with_links_intact(api):
    from app.models import Recipe, Routine, WorkoutSet
    from app.services import recipes as rc, routines as rt, workouts as wk
    maker = next(iter(api.app.dependency_overrides[get_db].__closure__)).cell_contents
    # build rich data for alice directly through the services
    a = user_db(maker, "alice")
    _opened.append(a)
    from app.models import Exercise
    ex = a.scalar(select(Exercise).limit(1))
    wk.log_sets(a, ex.id, [{"reps": 8, "weight_kg": 50}, {"reps": 8, "weight_kg": 52.5}])
    rt.save_routine(a, name="Push", exercises=[{"exercise_id": ex.id, "sets": 3, "rep_min": 8, "rep_max": 12, "rest_s": 90}])
    rc.save(a, name="Friday lentil pot", servings=2, ingredients=[{"name": "toor dal", "grams": 100}, {"name": "ghee", "grams": 10}])
    api.post("/api/meals", json={"name": "Paneer", "quantity": 2}, headers=h("alice"))
    api.post("/api/weight", json={"weight_kg": 91.5}, headers=h("alice"))
    backup = api.get("/api/export", headers=h("alice")).json()

    # bob already has his own data, with colliding ids; restoring into bob replaces it
    api.post("/api/meals", json={"name": "Chicken breast", "quantity": 1}, headers=h("bob"))
    bad = api.post("/api/me/import", json={"data": backup, "confirm": "nope"}, headers=h("bob"))
    assert bad.status_code == 422
    r = api.post("/api/me/import", json={"data": backup, "confirm": "REPLACE"}, headers=h("bob"))
    assert r.status_code == 200, r.text
    got = api.get("/api/export", headers=h("bob")).json()["tables"]
    assert [m["food_name"] for m in got["meal_logs"]] == ["Paneer"]
    assert [w["weight_kg"] for w in got["weight_log"]] == [91.5]
    # links survived re-numbering
    sets = got["workout_sets"]; sessions = got["workout_sessions"]
    assert len(sets) == 2 and {s["session_id"] for s in sets} == {sessions[0]["id"]}
    routine = got["routines"][0]; items = got["routine_exercises"]
    assert routine["name"] == "Push" and items[0]["routine_id"] == routine["id"]
    recipe = got["recipes"][0]; foods = {f["id"]: f["name"] for f in got["foods"]}
    assert foods[recipe["food_id"]] == "Friday lentil pot"
    # and alice is untouched
    assert len(api.get("/api/export", headers=h("alice")).json()["tables"]["workout_sets"]) == 2


def test_restore_rejects_junk_and_never_changes_owner(api):
    assert api.post("/api/me/import", json={"data": {"hello": 1}, "confirm": "REPLACE"}, headers=h("bob")).status_code == 422
    assert api.post("/api/me/import", json={"data": {"tables": {"meal_logs": []}}, "confirm": "REPLACE"}, headers=h("bob")).status_code == 422
    # a file that tries to plant rows in someone else's account
    evil = {"tables": {"meal_logs": [{"user_id": "alice", "food_name": "planted", "calories": 1, "protein_g": 1,
                                       "day": "2026-10-01", "logged_at": "2026-10-01T10:00:00", "quantity": 1}]}}
    assert api.post("/api/me/import", json={"data": evil, "confirm": "REPLACE"}, headers=h("bob")).status_code == 200
    assert [m["food_name"] for m in api.get("/api/export", headers=h("alice")).json()["tables"]["meal_logs"]] == []
    assert [m["food_name"] for m in api.get("/api/export", headers=h("bob")).json()["tables"]["meal_logs"]] == ["planted"]
    # a broken link rolls everything back
    broken = {"tables": {"meal_logs": [{"food_name": "ok", "calories": 1, "protein_g": 1}],
                         "workout_sets": [{"session_id": 999, "exercise_id": "x", "reps": 1}]}}
    assert api.post("/api/me/import", json={"data": broken, "confirm": "REPLACE"}, headers=h("bob")).status_code == 422
    assert [m["food_name"] for m in api.get("/api/export", headers=h("bob")).json()["tables"]["meal_logs"]] == ["planted"]
