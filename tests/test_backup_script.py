"""
Tests for scripts/backup_db.py.

Two things get real (not mocked) exercise, since the whole point of a
backup script is "does it actually produce a usable backup", not "did
the right functions get called":
  - SQLite: always, via Python's built-in sqlite3 module.
  - PostgreSQL: only when `pg_dump` is on PATH and TEST_DATABASE_URL
    points at a reachable Postgres server (the same env var
    tests/conftest.py uses) — skipped otherwise, so the suite stays
    fully runnable without PostgreSQL installed.
"""

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.backup_db import (  # noqa: E402
    PROJECT_ROOT,
    _parse_postgres_url,
    _prune_old_backups,
    _sqlite_path_from_url,
    backup,
)

PG_AVAILABLE = shutil.which("pg_dump") is not None
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")
POSTGRES_REACHABLE = PG_AVAILABLE and TEST_DATABASE_URL.startswith("postgresql")


def test_absolute_url_four_slashes_parses_as_absolute():
    result = _sqlite_path_from_url("sqlite:////home/someone/data/shrine.db")
    assert result == Path("/home/someone/data/shrine.db")


def test_relative_url_three_slashes_resolves_against_project_root():
    result = _sqlite_path_from_url("sqlite:///./shrine.db")
    assert result == (PROJECT_ROOT / "./shrine.db").resolve()
    assert result == PROJECT_ROOT / "shrine.db"


def test_relative_url_without_dot_slash_also_resolves_correctly():
    result = _sqlite_path_from_url("sqlite:///shrine.db")
    assert result == PROJECT_ROOT / "shrine.db"


def test_unsupported_scheme_is_rejected_by_the_dispatcher(monkeypatch):
    class _FakeSettings:
        DATABASE_URL = "mysql://user:pass@host/db"

    monkeypatch.setattr("scripts.backup_db.get_settings", lambda: _FakeSettings())
    with pytest.raises(ValueError, match="Don't know how to back up"):
        backup()


def test_backup_produces_a_working_copy_with_the_same_data(tmp_path, monkeypatch):
    # Build a tiny real SQLite DB to back up.
    source = tmp_path / "source.db"
    conn = sqlite3.connect(str(source))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO t (value) VALUES ('hello')")
    conn.commit()
    conn.close()

    backup_dir = tmp_path / "backups"
    monkeypatch.setattr("scripts.backup_db.BACKUP_DIR", backup_dir)

    class _FakeSettings:
        DATABASE_URL = f"sqlite:///{source}"

    monkeypatch.setattr("scripts.backup_db.get_settings", lambda: _FakeSettings())

    dest = backup()

    assert dest.exists()
    assert dest.parent == backup_dir
    check = sqlite3.connect(str(dest))
    rows = check.execute("SELECT value FROM t").fetchall()
    check.close()
    assert rows == [("hello",)]


def test_backup_raises_clearly_when_source_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.backup_db.BACKUP_DIR", tmp_path / "backups")

    class _FakeSettings:
        DATABASE_URL = f"sqlite:///{tmp_path / 'does-not-exist.db'}"

    monkeypatch.setattr("scripts.backup_db.get_settings", lambda: _FakeSettings())

    with pytest.raises(FileNotFoundError, match="Nothing to back up"):
        backup()


def test_keep_prunes_older_backups(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setattr("scripts.backup_db.BACKUP_DIR", backup_dir)

    # Four dummy backup files with controlled, distinct mtimes — no
    # need to actually run backup() four times with real sleeps just to
    # get different timestamps.
    now = 1_700_000_000
    files = []
    for i in range(4):
        f = backup_dir / f"shrine-2026010{i}-000000.db"
        f.write_bytes(b"x")
        os.utime(f, (now + i, now + i))
        files.append(f)

    _prune_old_backups(keep=2, pattern="shrine-????????-??????.db")

    remaining = {p.name for p in backup_dir.glob("shrine-*.db")}
    assert remaining == {files[-1].name, files[-2].name}  # the two most recently modified


def test_prune_only_matches_its_own_pattern(tmp_path):
    """Pruning SQLite backups must never touch Postgres dump files (and vice versa)."""
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "shrine-20260101-000000.db").write_bytes(b"x")
    (backup_dir / "shrine-pg-20260101-000000.dump").write_bytes(b"x")

    import scripts.backup_db as bd

    bd.BACKUP_DIR = backup_dir
    _prune_old_backups(keep=0, pattern="shrine-????????-??????.db")

    remaining = {p.name for p in backup_dir.glob("*")}
    assert remaining == {"shrine-pg-20260101-000000.dump"}


# ---------------------------------------------------------------- Postgres


def test_parse_postgres_url_extracts_components():
    result = _parse_postgres_url("postgresql+psycopg2://shrine:secret@dbhost:5433/shrinedb")
    assert result == {
        "host": "dbhost",
        "port": "5433",
        "user": "shrine",
        "password": "secret",
        "dbname": "shrinedb",
    }


def test_parse_postgres_url_defaults_port():
    result = _parse_postgres_url("postgresql://user:pw@host/db")
    assert result["port"] == "5432"


def test_postgres_backup_raises_clearly_when_pg_dump_missing(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)

    class _FakeSettings:
        DATABASE_URL = "postgresql://user:pw@localhost/db"

    monkeypatch.setattr("scripts.backup_db.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("scripts.backup_db.BACKUP_DIR", Path("/tmp"))

    with pytest.raises(RuntimeError, match="pg_dump not found"):
        backup()


def test_postgres_backup_raises_clearly_on_pg_dump_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/pg_dump")

    def _fake_run(cmd, env, check, capture_output, text):
        raise subprocess.CalledProcessError(1, cmd, stderr="connection refused")

    monkeypatch.setattr("scripts.backup_db.subprocess.run", _fake_run)

    class _FakeSettings:
        DATABASE_URL = "postgresql://user:pw@localhost/db"

    monkeypatch.setattr("scripts.backup_db.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("scripts.backup_db.BACKUP_DIR", tmp_path)

    with pytest.raises(RuntimeError, match="connection refused"):
        backup()

    # no partial/zero-byte dump file left behind
    assert list(tmp_path.glob("shrine-pg-*.dump")) == []


@pytest.mark.skipif(not POSTGRES_REACHABLE, reason="requires pg_dump and TEST_DATABASE_URL pointing at Postgres")
def test_postgres_backup_produces_a_restorable_dump(tmp_path, monkeypatch):
    """
    The real thing: back up a live Postgres database with pg_dump, then
    actually restore it into a throwaway database with pg_restore and
    confirm the data round-trips. Not mocked — a script whose entire
    job is "produce a usable backup" needs to prove it produces one.
    """
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr("scripts.backup_db.BACKUP_DIR", backup_dir)

    class _FakeSettings:
        DATABASE_URL = TEST_DATABASE_URL

    monkeypatch.setattr("scripts.backup_db.get_settings", lambda: _FakeSettings())

    conn_info = _parse_postgres_url(TEST_DATABASE_URL)
    env = os.environ.copy()
    if conn_info["password"]:
        env["PGPASSWORD"] = conn_info["password"]

    # Seed one real row in the source database.
    import psycopg2

    conn = psycopg2.connect(TEST_DATABASE_URL.replace("+psycopg2", ""))
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS backup_script_probe (id SERIAL PRIMARY KEY, value TEXT)")
    cur.execute("DELETE FROM backup_script_probe")
    cur.execute("INSERT INTO backup_script_probe (value) VALUES ('round-trip-check')")
    conn.close()

    dest = backup()
    assert dest.exists()

    restore_db = f"{conn_info['dbname']}_restore_probe"
    admin_conn = psycopg2.connect(TEST_DATABASE_URL.replace("+psycopg2", "").rsplit("/", 1)[0] + "/postgres")
    admin_conn.autocommit = True
    admin_cur = admin_conn.cursor()
    admin_cur.execute(f'DROP DATABASE IF EXISTS "{restore_db}"')
    admin_cur.execute(f'CREATE DATABASE "{restore_db}" OWNER "{conn_info["user"]}"')
    admin_conn.close()

    try:
        subprocess.run(
            ["pg_restore", "-h", conn_info["host"], "-p", conn_info["port"], "-U", conn_info["user"],
             "-d", restore_db, str(dest)],  # fmt: skip
            env=env, check=True, capture_output=True, text=True,
        )
        restored = psycopg2.connect(
            f"postgresql://{conn_info['user']}:{conn_info['password']}@{conn_info['host']}:{conn_info['port']}/{restore_db}"
        )
        cur = restored.cursor()
        cur.execute("SELECT value FROM backup_script_probe")
        rows = cur.fetchall()
        restored.close()
        assert rows == [("round-trip-check",)]
    finally:
        admin_conn = psycopg2.connect(TEST_DATABASE_URL.replace("+psycopg2", "").rsplit("/", 1)[0] + "/postgres")
        admin_conn.autocommit = True
        admin_conn.cursor().execute(f'DROP DATABASE IF EXISTS "{restore_db}"')
        admin_conn.close()
