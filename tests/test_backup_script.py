"""
Tests for scripts/backup_db.py.

Focused on _sqlite_path_from_url — the part with a real, easy-to-get-
wrong subtlety (SQLAlchemy's 3-slash-vs-4-slash relative/absolute
convention, which plain urllib.parse.urlparse does not understand).
The actual backup() function is exercised via the real SQLite backup
API against a temp file rather than mocked, since the whole point of
this script is "does the online backup actually produce a working copy".
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.backup_db import PROJECT_ROOT, _sqlite_path_from_url, backup  # noqa: E402


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


def test_non_sqlite_url_is_rejected():
    with pytest.raises(ValueError, match="not SQLite"):
        _sqlite_path_from_url("postgresql://user:pass@host/db")


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
    import os

    from scripts.backup_db import _prune_old_backups

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

    _prune_old_backups(keep=2)

    remaining = {p.name for p in backup_dir.glob("shrine-*.db")}
    assert remaining == {files[-1].name, files[-2].name}  # the two most recently modified
