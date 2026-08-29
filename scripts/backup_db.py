#!/usr/bin/env python3
"""
Back up SHRINE's database.

Dispatches based on DATABASE_URL's scheme — the same "one command
regardless of environment" pattern `alembic upgrade head` already uses:

  - sqlite:///...   -> SQLite's own online backup API (via Python's
                       sqlite3 module). Safe to run while the app is
                       live: copies page-by-page under SQLite's own
                       locking, unlike a plain file copy, which risks
                       grabbing a half-written page mid-copy.
  - postgresql://... -> `pg_dump` in custom format (-Fc): compressed,
                        and restorable selectively/in parallel via
                        `pg_restore`. Requires the PostgreSQL client
                        tools to be installed (`pg_dump` on PATH) —
                        these are NOT a Python dependency, so they
                        aren't in requirements.txt; install via your
                        OS package manager (e.g. `apt install
                        postgresql-client`) if missing.

Usage:
    python scripts/backup_db.py
    python scripts/backup_db.py --keep 10   # also prune older backups of the SAME type, keeping the 10 most recent
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Make "app" importable when this script is run directly (it isn't run
# as part of the app's own package) — same pattern as alembic/env.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402

BACKUP_DIR = PROJECT_ROOT / "backups"


# ------------------------------------------------------------------ SQLite


def _sqlite_path_from_url(database_url: str) -> Path:
    """
    Parse a SQLAlchemy SQLite URL into a filesystem path.

    NOT done with urllib.parse.urlparse — it doesn't know SQLAlchemy's
    convention that the slash count is meaningful:
        sqlite:///relative/path.db   (3 slashes -> relative)
        sqlite:////absolute/path.db  (4 slashes -> absolute)
    urlparse treats both as an absolute path, silently corrupting the
    relative case (e.g. "sqlite:///./shrine.db" -> "/./shrine.db",
    resolving to "/shrine.db" at the filesystem root — very wrong).
    """
    prefix = "sqlite:///"
    remainder = database_url[len(prefix) :]
    if remainder.startswith("/"):
        return Path(remainder).resolve()  # was 4 slashes total -> already absolute

    # Was 3 slashes total -> relative. SQLite itself resolves this
    # relative to the process's current working directory at connect
    # time; this script assumes that's the project root, matching how
    # README.md documents running the app (`uvicorn app.main:app` from
    # the repo root).
    return (PROJECT_ROOT / remainder).resolve()


def _backup_sqlite(database_url: str) -> Path:
    source_path = _sqlite_path_from_url(database_url)
    if not source_path.exists():
        raise FileNotFoundError(
            f"No database found at {source_path}. Nothing to back up yet — "
            "run `alembic upgrade head` first if this is a fresh setup."
        )

    dest_path = BACKUP_DIR / f"shrine-{_timestamp()}.db"
    source_conn = sqlite3.connect(str(source_path))
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    print(f"Backed up {source_path} -> {dest_path} ({_size_kb(dest_path)} KB)")
    return dest_path


# ---------------------------------------------------------------- Postgres


def _parse_postgres_url(database_url: str) -> dict:
    # Strip the SQLAlchemy-specific driver suffix (+psycopg2) — libpq
    # (which pg_dump uses) only understands the plain postgresql:// scheme.
    normalized = database_url.replace("postgresql+psycopg2", "postgresql")
    parsed = urlparse(normalized)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/"),
    }


def _backup_postgres(database_url: str) -> Path:
    if shutil.which("pg_dump") is None:
        raise RuntimeError(
            "pg_dump not found on PATH. Install the PostgreSQL client tools "
            "(e.g. `apt install postgresql-client` / `brew install postgresql`) and try again."
        )

    conn = _parse_postgres_url(database_url)
    dest_path = BACKUP_DIR / f"shrine-pg-{_timestamp()}.dump"

    # Password via environment, never on the command line — command-line
    # arguments are visible to other local users via `ps`; environment
    # variables passed only to this one subprocess are not.
    env = os.environ.copy()
    if conn["password"]:
        env["PGPASSWORD"] = conn["password"]

    cmd = [
        "pg_dump",
        "-h", conn["host"],
        "-p", conn["port"],
        "-U", conn["user"],
        "-Fc",  # custom format: compressed, supports selective/parallel restore via pg_restore
        "-f", str(dest_path),
        conn["dbname"],
    ]  # fmt: skip

    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        dest_path.unlink(missing_ok=True)  # don't leave a zero-byte/partial dump behind
        raise RuntimeError(f"pg_dump failed: {exc.stderr.strip()}") from exc

    print(f"Backed up {conn['dbname']}@{conn['host']} -> {dest_path} ({_size_kb(dest_path)} KB)")
    return dest_path


# -------------------------------------------------------------- dispatch


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _size_kb(path: Path) -> str:
    return f"{path.stat().st_size / 1024:.1f}"


def backup(keep: int | None = None) -> Path:
    settings = get_settings()
    database_url = settings.DATABASE_URL
    BACKUP_DIR.mkdir(exist_ok=True)

    if database_url.startswith("sqlite:///"):
        dest_path = _backup_sqlite(database_url)
        pattern = "shrine-????????-??????.db"  # excludes shrine-pg-*.dump
    elif database_url.startswith(("postgresql://", "postgresql+psycopg2://", "postgres://")):
        dest_path = _backup_postgres(database_url)
        pattern = "shrine-pg-*.dump"
    else:
        raise ValueError(
            f"Don't know how to back up DATABASE_URL {database_url!r} — only sqlite:// and "
            "postgresql:// are supported."
        )

    if keep is not None:
        _prune_old_backups(keep, pattern)

    return dest_path


def _prune_old_backups(keep: int, pattern: str) -> None:
    """Keep the `keep` most recently modified backups matching `pattern`, deleting the rest."""
    backups = sorted(BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        stale.unlink()
        print(f"Removed old backup: {stale.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, default=None, metavar="N", help="Keep only the N most recent backups.")
    args = parser.parse_args()

    try:
        backup(keep=args.keep)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
