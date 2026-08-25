"""
Shared pytest fixtures.

Tests run against a throwaway SQLite file (created fresh per test
session, deleted after) instead of the real shrine.db. The FastAPI
`get_db` dependency is overridden to hand out sessions bound to that
test database, so running the test suite never reads or writes real
content. This pattern is set up now, before any models exist, so every
future test in Phase 2+ can reuse it unchanged.
"""

import os
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base, get_db
from app.main import app


@pytest.fixture(scope="session")
def test_engine():
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
