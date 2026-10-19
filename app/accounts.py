"""Account plumbing: database setup, first-sign-in provisioning, the pause switch, export and delete."""
import base64
import hashlib
import logging
import threading
import time
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import Date, DateTime, delete, func, select
from sqlalchemy.orm import Session

from . import clock
from .auth import AuthUser
from .config import get_settings
from .db import Base, engine as default_engine
from .migrate import ensure_columns, upgrade_to_accounts
from .models import ChatMessage, Profile, SiteSetting, UserSecret
from .seed.loader import SEED_VERSION, seed_exercises, seed_user

log = logging.getLogger("fitchat.accounts")

_init_lock = threading.Lock()
_initialised = False
_ready_users: set[str] = set()
_paused_cache: tuple[float, bool] = (0.0, False)
PAUSE_TTL_S = 10


# ---------- database setup ----------
def init_database(engine=None) -> list[str]:
    """Create/upgrade tables and load shared reference data. Safe to run any number of times."""
    engine = engine or default_engine
    ensure_columns(engine)  # old laptop databases first (adds columns the rebuild copies)
    rebuilt = upgrade_to_accounts(engine)
    Base.metadata.create_all(engine)
    lock_down_postgres(engine)
    with Session(engine) as s:
        seed_exercises(s)
    return rebuilt


def lock_down_postgres(engine) -> None:
    """Supabase publishes every table in the public schema through its own web API, readable by anyone holding the
    (public) anon key. Our data must only ever be reached through this server, so switch row-level security on for
    every table with no policies (= nobody but the server's own database login can read or write) and take away
    the anon/authenticated roles' rights."""
    if engine.dialect.name != "postgresql":
        return
    with engine.begin() as conn:
        for t in Base.metadata.sorted_tables:
            conn.exec_driver_sql(f'ALTER TABLE "{t.name}" ENABLE ROW LEVEL SECURITY')
        conn.exec_driver_sql("""
            DO $$
            DECLARE r text;
            BEGIN
              FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                  EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %%I', r);
                  EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %%I', r);
                END IF;
              END LOOP;
            END $$;""")


_failed_at = 0.0


def ensure_initialised() -> None:
    global _initialised, _failed_at
    if _initialised or not get_settings().auto_migrate:
        return
    with _init_lock:
        if _initialised:
            return
        if _failed_at and time.monotonic() - _failed_at < 120:
            # Do not hammer the database with a wrong password: Supabase blocks repeated failures.
            raise RuntimeError("Database setup failed a moment ago; waiting before trying again (see the logs).")
        try:
            rebuilt = init_database()
            if rebuilt:
                log.info("Database upgraded for accounts; your existing data now belongs to the local user: %s",
                         ", ".join(rebuilt))
            _initialised = True
            _failed_at = 0.0
        except Exception:  # e.g. two cold starts racing to create tables; retried after a short pause
            _failed_at = time.monotonic()
            log.exception("database setup failed")
            raise


# ---------- per-request preparation ----------
def prepare(db: Session, user: AuthUser) -> None:
    ensure_initialised()
    if user.uid not in _ready_users:
        profile = db.scalar(select(Profile))
        if profile is None or (profile.seed_version or 0) < SEED_VERSION:
            seed_user(db)
        _ready_users.add(user.uid)
    if not user.is_admin and is_paused(db):
        raise HTTPException(503, "FitChat is paused for now. Please check back later.")


def forget_user(uid: str) -> None:
    _ready_users.discard(uid)


# ---------- pause switch ----------
def is_paused(db: Session, fresh: bool = False) -> bool:
    global _paused_cache
    t, val = _paused_cache
    if not fresh and t > time.monotonic():
        return val
    row = db.get(SiteSetting, "paused")
    val = bool(row and row.value == "1")
    _paused_cache = (time.monotonic() + PAUSE_TTL_S, val)
    return val


def set_paused(db: Session, paused: bool) -> None:
    global _paused_cache
    row = db.get(SiteSetting, "paused")
    if row is None:
        db.add(SiteSetting(key="paused", value="1" if paused else "0"))
    else:
        row.value = "1" if paused else "0"
    db.commit()
    _paused_cache = (time.monotonic() + PAUSE_TTL_S, paused)


# ---------- the user's own Gemini key ----------
def _fernet():
    from cryptography.fernet import Fernet

    secret = get_settings().app_secret
    if not secret:
        return None
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def byok_available() -> bool:
    return _fernet() is not None


def save_own_key(db: Session, key: str) -> None:
    f = _fernet()
    if f is None:
        raise HTTPException(503, "Saving your own key isn't enabled on this server.")
    row = db.scalar(select(UserSecret))
    token = f.encrypt(key.strip().encode()).decode()
    if row is None:
        db.add(UserSecret(gemini_key_enc=token))
    else:
        row.gemini_key_enc = token
    db.commit()


def clear_own_key(db: Session) -> None:
    db.execute(delete(UserSecret))
    db.commit()


def own_key(db: Session) -> str | None:
    f = _fernet()
    row = db.scalar(select(UserSecret))
    if f is None or row is None or not row.gemini_key_enc:
        return None
    try:
        return f.decrypt(row.gemini_key_enc.encode()).decode()
    except Exception:
        return None


# ---------- chat allowance ----------
def chat_used_today(db: Session) -> int:
    start = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(ChatMessage)
                     .where(ChatMessage.role == "user", ChatMessage.created_at >= start)) or 0


def chat_allowance(db: Session, user: AuthUser) -> dict:
    limit = get_settings().daily_chat_limit
    mine = own_key(db) is not None
    unlimited = mine or user.uid == "local" or user.is_admin
    return {"used": chat_used_today(db), "limit": None if unlimited else limit, "own_key": mine,
            "own_key_available": byok_available()}


# ---------- export / delete ----------
def _user_tables():
    return [t for t in Base.metadata.sorted_tables if "user_id" in t.c and t.name != "user_secrets"]


def export_data(db: Session) -> dict:
    uid = db.info["uid"]
    out: dict = {"exported_at": clock.now().isoformat(timespec="seconds"), "tables": {}}
    for t in _user_tables():
        rows = db.execute(select(t).where(t.c.user_id == uid)).mappings().all()
        out["tables"][t.name] = [{k: v for k, v in r.items() if k != "user_id"} for r in rows]
    return out


def delete_data(db: Session) -> int:
    uid = db.info["uid"]
    n = 0
    for t in reversed(Base.metadata.sorted_tables):
        if "user_id" in t.c:
            n += db.execute(delete(t).where(t.c.user_id == uid)).rowcount or 0
    db.commit()
    forget_user(uid)
    return n


# ---------- restore from a backup (also how laptop data moves to a hosted account) ----------
MAX_IMPORT_ROWS = 200_000
# (table, column) pairs that point at another table's id. Ids are re-assigned on import, so these are re-pointed.
_LINKS = {("recipes", "food_id"): "foods", ("workout_sets", "session_id"): "workout_sessions",
          ("routine_exercises", "routine_id"): "routines"}


def _coerce(col, v):
    if v is None:
        return None
    if isinstance(col.type, DateTime) and isinstance(v, str):
        return datetime.fromisoformat(v)
    if isinstance(col.type, Date) and isinstance(v, str):
        return date.fromisoformat(v[:10])
    return v


def import_data(db: Session, payload: dict) -> dict:
    """Replace this user's data with the contents of an export file. Only this user's rows are touched, and the file
    can never set who owns a row. Nothing is changed if the file is not a valid FitChat export."""
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, dict) or not tables:
        raise ValueError("That is not a FitChat backup file.")
    known = {t.name: t for t in _user_tables()}
    total = sum(len(rows) for name, rows in tables.items() if name in known and isinstance(rows, list))
    if total == 0:
        raise ValueError("That backup file has no data in it.")
    if total > MAX_IMPORT_ROWS:
        raise ValueError("That backup file is too large.")
    uid = db.info["uid"]
    try:
        for t in reversed(Base.metadata.sorted_tables):  # wipe my current data
            if "user_id" in t.c:
                db.execute(delete(t).where(t.c.user_id == uid))
        idmap: dict[str, dict] = {}
        counts: dict[str, int] = {}
        for t in _user_tables():  # parents before children
            rows = tables.get(t.name)
            if not isinstance(rows, list):
                continue
            auto_id = "id" in t.c and t.c.id.primary_key
            for r in rows:
                if not isinstance(r, dict):
                    raise ValueError(f"Bad row in {t.name}.")
                vals = {}
                for k, v in r.items():
                    if k == "user_id" or k not in t.c or (k == "id" and auto_id):
                        continue
                    vals[k] = _coerce(t.c[k], v)
                for (tn, col), parent in _LINKS.items():
                    if tn == t.name and col in vals:
                        new = idmap.get(parent, {}).get(vals[col])
                        if new is None:
                            raise ValueError(f"{t.name} refers to a missing {parent} row.")
                        vals[col] = new
                vals["user_id"] = uid
                res = db.execute(t.insert().values(**vals))
                if auto_id and "id" in r:
                    idmap.setdefault(t.name, {})[r["id"]] = res.inserted_primary_key[0]
            counts[t.name] = len(rows)
        db.commit()
    except Exception:
        db.rollback()
        raise
    forget_user(uid)
    return {"restored_rows": sum(counts.values()), "tables": counts}
