"""
Shared pytest fixtures.

Tests run against a throwaway SQLite file — a fresh one for every test
function, deleted after — instead of the real shrine.db. The FastAPI
`get_db` dependency is overridden to hand out sessions bound to that
test database, so running the test suite never reads or writes real
content, and no test can see another test's data.
"""

import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  registers all models on Base.metadata — see app/models/__init__.py
from app.db.database import Base, get_db
from app.main import app


@pytest.fixture()
def test_engine():
    """
    A fresh, empty SQLite file for every single test function.

    This fixture is intentionally function-scoped, not session-scoped:
    a shared database across the whole test run would let one test's
    data leak into another's (e.g. a work created in one test showing
    up in a different test's "list published works" assertion) —
    exactly the kind of bug that stays invisible until a test happens
    to assert on page content broadly, then fails for a confusing
    reason. A fresh file per test costs a few milliseconds and buys
    real isolation.
    """
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()
    os.close(db_fd)
    os.remove(db_path)


@pytest.fixture()
def db_session(test_engine) -> Generator:
    """A raw session for tests that exercise repositories/services directly."""
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(test_engine) -> Generator[TestClient, None, None]:
    """A FastAPI TestClient wired to the throwaway test database."""
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
