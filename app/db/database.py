"""
Database engine and session management.

This is the ONLY file in the application that should know anything about
SQLAlchemy engine configuration. Repositories receive a `Session` and
never construct their own connections — that's what keeps the eventual
SQLite -> PostgreSQL swap to a one-line change in `.env`, instead of a
search-and-replace through the codebase.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# SQLite needs `check_same_thread=False` because FastAPI can hand a
# request to a different thread than the one that opened the connection.
# This flag is meaningless (and unused) for PostgreSQL, so it's applied
# conditionally rather than baked in as a default — the goal is that
# switching DATABASE_URL to a postgresql:// value requires no edits here.
connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    # Verifies a pooled connection is still alive before handing it out.
    # Cheap for SQLite, and prevents "server closed the connection"
    # errors once this points at a real PostgreSQL server.
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base class for all ORM models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a database session for the lifetime of
    a single request, and guarantees it is closed afterward — including
    when the request handler raises.

    Usage:
        @router.get("/works")
        def list_works(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
