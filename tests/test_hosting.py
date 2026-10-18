"""Hosting: upgrading a laptop database, signing in, the pause switch, chat limits, own Gemini key, time zones."""
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import accounts, auth, clock
from app.config import get_settings
from app.db import Base, open_session
from app.llm.fake import ScriptedLLM
from app.main import app
from app.models import Food, MealLog, Routine, WeightLog, WorkoutSession
from app.seed.loader import seed_exercises, seed_user


# ---------- upgrading an existing laptop database ----------
def test_old_database_is_upgraded_and_keeps_all_data(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript((Path(__file__).parent / "legacy_schema.sql").read_text())
    con.execute("INSERT INTO profile (id, goal, calorie_target, protein_target_g, weight_kg, experience, water_target_ml,"
                " fibre_target_g, gym_days_goal) VALUES (1,'fat_loss',2000,120,95,'beginner',3000,30,5)")
    con.execute("INSERT INTO foods (id,name,aliases,serving,calories,protein_g,carbs_g,fat_g,fibre_g,source)"
                " VALUES (1,'My shake','[]','1 glass',300,30,10,5,1,'user')")
    con.execute("INSERT INTO ingredients (id,name,aliases,calories_100g,protein_100g,carbs_100g,fat_100g,fibre_100g,source)"
                " VALUES (1,'Rajma','[]',127,8.7,22,0.5,6,'seed_approx')")
    con.execute("INSERT INTO meal_logs (id,logged_at,day,food_name,quantity,calories,protein_g,carbs_g,fat_g,fibre_g,estimated)"
                " VALUES (1,'2026-10-10 09:00:00','2026-10-10','My shake',1,300,30,10,5,1,0)")
    con.execute("INSERT INTO weight_log (day, weight_kg) VALUES ('2026-10-10', 96.5)")
    con.execute("INSERT INTO exercises (id,name,category,primary_muscles,secondary_muscles,instructions,images)"
                " VALUES ('bench','Bench Press','strength','[\"chest\"]','[]','[]','[]')")
    con.execute("INSERT INTO workout_sessions (id,day) VALUES (1,'2026-10-10')")
    con.execute("INSERT INTO workout_sets (id,session_id,exercise_id,set_number,reps,weight_kg) VALUES (1,1,'bench',1,8,60)")
    con.execute("INSERT INTO routines (id,name,created_at) VALUES (1,'Push','2026-10-01 10:00:00')")
    con.execute("INSERT INTO routine_exercises (id,routine_id,exercise_id,position,sets,rep_min,rep_max,rest_s)"
                " VALUES (1,1,'bench',0,3,8,12,90)")
    con.commit(); con.close()

    engine = create_engine(f"sqlite:///{path}")
    rebuilt = accounts.init_database(engine)
    assert "foods" in rebuilt and "weight_log" in rebuilt and "routine_exercises" in rebuilt

    db = open_session("local", sessionmaker(bind=engine, expire_on_commit=False, autoflush=False))
    assert db.scalar(select(Food).where(Food.name == "My shake")).user_id == "local"
    assert db.scalar(select(MealLog)).food_name == "My shake"
    assert db.scalar(select(WeightLog)).weight_kg == 96.5
    sess = db.scalar(select(WorkoutSession))
    assert [(s.reps, s.weight_kg, s.exercise.name) for s in sess.sets] == [(8, 60.0, "Bench Press")]
    r = db.scalar(select(Routine))
    assert r.name == "Push" and len(r.items) == 1
    # another person sees none of it, and can use the same names
    other = open_session("someone-else", sessionmaker(bind=engine, expire_on_commit=False, autoflush=False))
    assert other.scalars(select(MealLog)).all() == []
    seed_user(other)
    other.add(Routine(name="Push")); other.commit()
    # running the upgrade again changes nothing
    assert accounts.init_database(engine) == []


# ---------- signing in ----------
@pytest.fixture()
def hosted(monkeypatch):
    """The real sign-in chain with Supabase replaced by a stub, on an in-memory database."""
    s = get_settings()
    monkeypatch.setattr(s, "auth_mode", "supabase"); monkeypatch.setattr(s, "supabase_url", "https://x.supabase.co")
    monkeypatch.setattr(s, "supabase_anon_key", "anon"); monkeypatch.setattr(s, "admin_emails", "boss@example.com")
    monkeypatch.setattr(s, "app_secret", "test-secret"); monkeypatch.setattr(s, "daily_chat_limit", 2)
    monkeypatch.setattr(s, "auto_migrate", False)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    with maker() as sx:
        seed_exercises(sx)
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "SessionLocal", maker)
    import app.api.account as acc_api
    monkeypatch.setattr(acc_api, "SessionLocal", maker)
    monkeypatch.setattr(accounts, "_ready_users", set())
    monkeypatch.setattr(accounts, "_paused_cache", (0.0, False))
    auth._cache.clear()

    people = {
        "tok-alice": {"id": "uid-alice", "email": "alice@example.com", "email_confirmed_at": "2026-01-01"},
        "tok-bob": {"id": "uid-bob", "email": "bob@example.com", "email_confirmed_at": "2026-01-01"},
        "tok-boss": {"id": "uid-boss", "email": "boss@example.com", "email_confirmed_at": "2026-01-01"},
        "tok-fake-boss": {"id": "uid-fake", "email": "boss@example.com", "email_confirmed_at": None},
    }
    monkeypatch.setattr(auth, "_fetch_user", lambda token: people.get(token))
    holder = {"llm": ScriptedLLM([])}
    from app.deps import get_llm
    app.dependency_overrides[get_llm] = lambda: holder["llm"]
    c = TestClient(app)
    c.maker = maker; c.holder = holder
    yield c
    app.dependency_overrides.clear()
    auth._cache.clear()


def tok(t):
    return {"Authorization": f"Bearer {t}"}


def test_requests_without_a_valid_token_are_refused(hosted):
    assert hosted.get("/api/profile").status_code == 401
    assert hosted.get("/api/profile", headers=tok("garbage")).status_code == 401
    assert hosted.get("/api/profile", headers={"Authorization": "Basic abc"}).status_code == 401
    assert hosted.get("/api/profile", headers=tok("tok-alice")).status_code == 200


def test_first_sign_in_creates_starter_data_and_users_stay_apart(hosted):
    hosted.post("/api/meals", json={"name": "Paneer", "quantity": 1}, headers=tok("tok-alice"))
    a = hosted.get("/api/summary/today", headers=tok("tok-alice")).json()["totals"]["calories"]
    b = hosted.get("/api/summary/today", headers=tok("tok-bob")).json()["totals"]["calories"]
    assert a > 0 and b == 0
    foods = hosted.get("/api/foods", headers=tok("tok-bob")).json()
    assert len(foods) > 20


def test_public_config_needs_no_sign_in_and_only_exposes_public_values(hosted):
    j = hosted.get("/api/config").json()
    assert j["auth"] == "supabase" and j["supabase_anon_key"] == "anon" and j["photos"] is False
    assert "app_secret" not in str(j) and "gemini" not in str(j).lower()


def test_only_a_confirmed_admin_email_is_admin(hosted):
    assert hosted.get("/api/me", headers=tok("tok-boss")).json()["admin"] is True
    assert hosted.get("/api/me", headers=tok("tok-alice")).json()["admin"] is False
    assert hosted.get("/api/me", headers=tok("tok-fake-boss")).json()["admin"] is False  # unconfirmed address


def test_pause_switch_blocks_everyone_but_the_owner(hosted):
    assert hosted.post("/api/admin/pause", json={"paused": True}, headers=tok("tok-alice")).status_code == 403
    assert hosted.post("/api/admin/pause", json={"paused": True}, headers=tok("tok-boss")).status_code == 200
    assert hosted.get("/api/config").json()["paused"] is True
    r = hosted.get("/api/profile", headers=tok("tok-alice"))
    assert r.status_code == 503 and "paused" in r.json()["detail"].lower()
    assert hosted.get("/api/profile", headers=tok("tok-boss")).status_code == 200
    hosted.post("/api/admin/pause", json={"paused": False}, headers=tok("tok-boss"))
    assert hosted.get("/api/profile", headers=tok("tok-alice")).status_code == 200


def test_daily_chat_limit_then_own_key_removes_it(hosted):
    from app.llm.base import LLMResponse
    hosted.holder["llm"] = ScriptedLLM([LLMResponse(text="hi", tool_calls=[])] * 10)
    for _ in range(2):
        assert hosted.post("/api/chat", json={"message": "hello"}, headers=tok("tok-alice")).status_code == 200
    r = hosted.post("/api/chat", json={"message": "hello"}, headers=tok("tok-alice"))
    assert r.status_code == 429 and "own free Gemini key" in r.json()["detail"]
    # another person is not affected
    assert hosted.post("/api/chat", json={"message": "hello"}, headers=tok("tok-bob")).status_code == 200
    # adding their own key lifts the limit
    assert hosted.put("/api/me/gemini-key", json={"key": "AIza" + "x" * 30}, headers=tok("tok-alice")).status_code == 200
    me = hosted.get("/api/me", headers=tok("tok-alice")).json()["chat"]
    assert me["own_key"] is True and me["limit"] is None
    assert hosted.post("/api/chat", json={"message": "hello"}, headers=tok("tok-alice")).status_code == 200
    assert hosted.delete("/api/me/gemini-key", headers=tok("tok-alice")).status_code == 204
    assert hosted.get("/api/me", headers=tok("tok-alice")).json()["chat"]["limit"] == 2


def test_own_key_is_stored_encrypted_and_private(hosted):
    key = "AIza" + "q" * 30
    hosted.put("/api/me/gemini-key", json={"key": key}, headers=tok("tok-alice"))
    with hosted.maker() as s:
        raw = s.execute(text("select gemini_key_enc from user_secrets")).scalar()
    assert raw and key not in raw
    out = hosted.get("/api/export", headers=tok("tok-alice")).json()
    assert key not in str(out) and "user_secrets" not in out["tables"]
    s = open_session("uid-alice", hosted.maker)
    assert accounts.own_key(s) == key
    assert accounts.own_key(open_session("uid-bob", hosted.maker)) is None


# ---------- time zone ----------
def test_today_follows_the_callers_time_zone(monkeypatch):
    import datetime as dt
    real = dt.datetime
    class Fixed(real):
        @classmethod
        def now(cls, tz=None):
            base = real(2026, 10, 17, 20, 0, tzinfo=dt.timezone.utc)  # 20:00 UTC = 01:30 next day in India
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)
    monkeypatch.setattr(clock, "datetime", Fixed)
    clock.set_tz("Asia/Kolkata")
    assert clock.today() == date(2026, 10, 18)
    clock.set_tz("America/New_York")
    assert clock.today() == date(2026, 10, 17)
    clock.set_tz("Not/AZone")  # ignored, falls back
    clock.set_tz(None)
    assert clock.today() == date(2026, 10, 17)
