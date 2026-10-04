"""Database: schema, the phase-1 hand-over, sessions and settings."""

from __future__ import annotations

import sqlite3

from app import db


def test_init_is_idempotent(env):
    assert db.init_db(env.db_path) is None
    assert db.init_db(env.db_path) is None


def test_a_phase_1_database_is_set_aside_never_deleted(env):
    old = sqlite3.connect(env.db_path)
    old.execute("CREATE TABLE links (token TEXT PRIMARY KEY, storage_ref TEXT)")
    old.execute("INSERT INTO links VALUES ('tok123', 'ref.bin')")
    old.commit()
    old.close()

    backup = db.init_db(env.db_path)

    assert backup is not None and backup.name == "test.db.phase1.bak"
    kept = sqlite3.connect(backup)
    assert kept.execute("SELECT token FROM links").fetchone() == ("tok123",), "old data intact"
    kept.close()
    fresh = db.connect(env.db_path)
    cols = {r[1] for r in fresh.execute("PRAGMA table_info(links)")}
    fresh.close()
    assert "drive_file_id" in cols and "token" not in cols


def test_sessions_store_only_a_hash(conn):
    raw = db.create_session(conn, hours=12)
    rows = conn.execute("SELECT * FROM admin_sessions").fetchall()
    assert len(rows) == 1 and raw not in dict(rows[0]).values()
    assert db.session_valid(conn, raw)
    assert not db.session_valid(conn, raw + "x")
    assert not db.session_valid(conn, None)
    assert not db.session_valid(conn, "")


def test_session_expiry_and_purge(conn):
    raw = db.create_session(conn, hours=12)
    conn.execute("UPDATE admin_sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    assert not db.session_valid(conn, raw)
    assert db.purge_expired_sessions(conn) == 1


def test_delete_session(conn):
    raw = db.create_session(conn, hours=12)
    db.delete_session(conn, raw)
    assert not db.session_valid(conn, raw)


def test_settings_upsert(conn):
    assert db.get_setting(conn, "k", "dflt") == "dflt"
    db.set_setting(conn, "k", "1")
    db.set_setting(conn, "k", "2")
    assert db.get_setting(conn, "k") == "2"
