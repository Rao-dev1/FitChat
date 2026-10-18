import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db, make_engine
from app.deps import get_llm
from app.main import app
from app.seed.loader import seed_all


@pytest.fixture()
def db():
    # TEST_DATABASE_URL=postgresql://... runs the whole suite against a real Postgres instead of in-memory SQLite.
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        engine = make_engine(url)
        Base.metadata.drop_all(engine)
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.info["uid"] = "test-user"
    seed_all(session)
    yield session
    session.close()
    if url:
        engine.dispose()


@pytest.fixture()
def client(db):
    """TestClient wired to the in-memory DB. Set client.llm = ScriptedLLM([...]) per test."""
    holder = {}
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_llm] = lambda: holder["llm"]
    c = TestClient(app)
    c.set_llm = lambda llm: holder.__setitem__("llm", llm)
    yield c
    app.dependency_overrides.clear()
