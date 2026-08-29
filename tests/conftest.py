"""
Shared pytest fixtures.

Tests run against a throwaway database — the exact backend is
controlled by the TEST_DATABASE_URL environment variable:

  - unset (default): a fresh temp SQLite file per test function,
    deleted after. Fast, zero external dependencies — the right
    default for everyday iteration.
  - set to a PostgreSQL URL: the exact same test suite runs against a
    real PostgreSQL server instead, proving the "swap DATABASE_URL,
    nothing else changes" architecture claim (see ARCHITECTURE.md)
    isn't just theoretical. Slower (real network round-trips for
    schema setup/teardown per test), so this is an occasional
    verification run, not the default.

Either way, the FastAPI `get_db` dependency is overridden to hand out
sessions bound to that test database, so running the test suite never
reads or writes real content, and no test can see another test's data.
"""

import os
import re
import tempfile
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  registers all models on Base.metadata — see app/models/__init__.py
from app.core.config import get_settings
from app.core.security import login_rate_limiter
from app.db.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _reset_login_rate_limiter():
    """
    login_rate_limiter (app/core/security.py) is a module-level
    singleton keyed by client IP — and every request through
    TestClient shares the same "testclient" IP. Without resetting it,
    a test that intentionally triggers a lockout would leak failed
    attempts into every other test's login calls. Same class of bug as
    the session-scoped test_engine fixture caught in Phase 3: shared
    global state across tests that are supposed to be independent.
    """
    login_rate_limiter._failures.clear()
    yield
    login_rate_limiter._failures.clear()


@pytest.fixture()
def test_engine():
    """
    A fresh, empty database for every single test function.

    Isolation matters more than raw speed here — a shared database
    across the whole test run would let one test's data leak into
    another's (e.g. a work created in one test showing up in a
    different test's "list published works" assertion), exactly the
    kind of bug the Phase 3 test-isolation fix was about. Both branches
    below guarantee a fresh schema per test; only the mechanism differs
    per backend (temp file vs. create/drop against a shared server).
    """
    if TEST_DATABASE_URL:
        engine = create_engine(TEST_DATABASE_URL)
        Base.metadata.create_all(bind=engine)
        yield engine
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
    else:
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
def services(db_session):
    """(WorkService, ChapterService) pair sharing one session — for tests that set up content directly."""
    from app.services.chapter_service import ChapterService
    from app.services.work_service import WorkService

    return WorkService(db_session), ChapterService(db_session)


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


def csrf_from(html: str) -> str:
    """Pull the csrf_token hidden-field value out of a rendered admin page."""
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "no csrf_token field found in page"
    return match.group(1)


@pytest.fixture()
def admin_client(client: TestClient) -> TestClient:
    """A `client` that has already logged in with the dev-default admin credentials."""
    settings = get_settings()
    login_page = client.get("/admin/login")
    response = client.post(
        "/admin/login",
        data={
            "username": settings.ADMIN_USERNAME,
            "password": "changeme123",  # matches the dev-only ADMIN_PASSWORD_HASH default
            "csrf_token": csrf_from(login_page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, "admin_client fixture failed to log in"
    return client
