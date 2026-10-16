import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.deps import get_llm
from app.main import app
from app.seed.loader import seed_all


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_all(session)
    yield session
    session.close()


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
