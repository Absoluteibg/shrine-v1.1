"""
Application configuration.

All environment-specific values (database location, secrets, debug flags)
live here and ONLY here. Nothing else in the app should call os.environ
directly — this keeps every environment-dependent value in one auditable
place, and makes it trivial to see what changes when we move from a laptop
to a real server, or from SQLite to PostgreSQL.

Settings are loaded from environment variables, with a `.env` file as a
convenience for local development. In production, real environment
variables should be set by the deployment platform instead of relying on
a .env file.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute path to the project root (the folder containing this repo),
# used to build safe absolute paths for the DB file, templates, and static
# assets regardless of the working directory the app is launched from.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # --- General ---
    APP_NAME: str = "SHRINE"
    ENV: str = "development"  # "development" | "production"
    DEBUG: bool = True

    # --- Database ---
    # SQLite now; swapping to PostgreSQL later is just changing this one
    # value to something like:
    #   postgresql+psycopg2://user:password@host:5432/shrine
    # No application code depends on the SQLite-specific URL format because
    # all DB access goes through SQLAlchemy (see app/db/database.py).
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'shrine.db'}"

    # --- Security ---
    # Used later for session signing / CSRF tokens once the admin CMS
    # (Phase 4) is built. Required with no default in production so a
    # deployment can never silently run with a predictable secret.
    SECRET_KEY: str = "dev-only-insecure-secret-change-me"

    # --- Paths ---
    TEMPLATES_DIR: Path = BASE_DIR / "templates"
    STATIC_DIR: Path = BASE_DIR / "static"
    IMAGES_DIR: Path = BASE_DIR / "static" / "images"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor.

    Use this (not `Settings()`) everywhere, including as a FastAPI
    dependency, so the environment is parsed once per process rather than
    re-read on every request.
    """
    return Settings()
