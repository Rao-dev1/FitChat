from collections.abc import Iterator

from fastapi import Depends

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .auth import AuthUser, current_user
from .config import get_settings


class Base(DeclarativeBase):
    pass


def normalize_url(url: str) -> str:
    """Accept the postgres:// style URL that hosts hand out and make it use the installed psycopg driver."""
    for old in ("postgres://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old):]
    return url


def make_engine(url: str):
    url = normalize_url(url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # Serverless hosting: every request may be a fresh process, and the database's own pooler (Supabase "transaction
    # pooler") manages connections, so don't keep our own pool. prepare_threshold=None because that pooler
    # does not support prepared statements.
    return create_engine(url, poolclass=NullPool, connect_args={"prepare_threshold": None})


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def open_session(uid: str | None, maker=None) -> Session:
    """A database session that can only see and write the given user's data."""
    db = (maker or SessionLocal)()
    if uid:
        db.info["uid"] = uid
    return db


def get_db(user: AuthUser = Depends(current_user)) -> Iterator[Session]:
    """One database session per request, bound to the signed-in user so it can only touch that user's data."""
    from . import accounts  # late import: accounts needs this module

    db = open_session(user.uid)
    db.info["user"] = user
    try:
        accounts.prepare(db, user)
        yield db
    finally:
        db.close()
