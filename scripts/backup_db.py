#!/usr/bin/env python3
"""
Back up SHRINE's SQLite database.

Uses SQLite's own online backup API (via Python's sqlite3 module),
which is safe to run even while the app is actively serving requests —
it copies page-by-page under SQLite's own locking, unlike a plain file
copy (`cp shrine.db backup.db`), which risks grabbing a half-written
page if a write happens mid-copy.

This script is deliberately SQLite-specific — the Stage 1 backup
strategy for this app (see ARCHITECTURE.md's scaling table). Migrating
to PostgreSQL later means switching to `pg_dump` or your host's managed
backup/snapshot tooling instead; this script doesn't grow to cover
that, it stops applying.

Usage:
    python scripts/backup_db.py
    python scripts/backup_db.py --keep 10   # also prune older backups, keeping the 10 most recent
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make "app" importable when this script is run directly (it isn't run
# as part of the app's own package) — same pattern as alembic/env.py.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402

BACKUP_DIR = PROJECT_ROOT / "backups"


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
    if not database_url.startswith(prefix):
        raise ValueError(
            f"DATABASE_URL is not SQLite ({database_url!r}). This script only backs up SQLite "
            "databases — for PostgreSQL, use `pg_dump` or your host's managed backup/snapshot "
            "tooling instead."
        )

    remainder = database_url[len(prefix) :]
    if remainder.startswith("/"):
        return Path(remainder).resolve()  # was 4 slashes total -> already absolute

    # Was 3 slashes total -> relative. SQLite itself resolves this
    # relative to the process's current working directory at connect
    # time; this script assumes that's the project root, matching how
    # README.md documents running the app (`uvicorn app.main:app` from
    # the repo root).
    return (PROJECT_ROOT / remainder).resolve()


def backup(keep: int | None = None) -> Path:
    settings = get_settings()
    source_path = _sqlite_path_from_url(settings.DATABASE_URL)

    if not source_path.exists():
        raise FileNotFoundError(
            f"No database found at {source_path}. Nothing to back up yet — "
            "run `alembic upgrade head` first if this is a fresh setup."
        )

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest_path = BACKUP_DIR / f"shrine-{timestamp}.db"

    source_conn = sqlite3.connect(str(source_path))
    dest_conn = sqlite3.connect(str(dest_path))
    try:
        source_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        source_conn.close()

    size_kb = dest_path.stat().st_size / 1024
    print(f"Backed up {source_path} -> {dest_path} ({size_kb:.1f} KB)")

    if keep is not None:
        _prune_old_backups(keep)

    return dest_path


def _prune_old_backups(keep: int) -> None:
    backups = sorted(BACKUP_DIR.glob("shrine-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for stale in backups[keep:]:
        stale.unlink()
        print(f"Removed old backup: {stale.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keep", type=int, default=None, metavar="N", help="Keep only the N most recent backups.")
    args = parser.parse_args()

    try:
        backup(keep=args.keep)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
