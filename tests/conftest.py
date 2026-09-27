"""Shared fixtures.

Every test runs against a throwaway SQLite file and a throwaway storage directory in
tmp_path, with STORAGE_BACKEND=local. Nothing here touches the network, so the suite
is runnable before the Google Drive account question is answered.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.main import app

SAMPLES = Path(__file__).resolve().parent.parent / "samples"

ADMIN_TOKEN = "test-admin-token"
AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("BASE_URL", "https://qr.test")
    monkeypatch.setenv("DEFAULT_EXPIRY_DAYS", "30")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def client(env):
    # `with` triggers the lifespan handler, which creates the schema and storage.
    with TestClient(app) as c:
        yield c


@pytest.fixture
def conn(env) -> sqlite3.Connection:
    db.init_db(env.db_path)
    c = db.connect(env.db_path)
    yield c
    c.close()


@pytest.fixture
def sample_pdfs() -> list[Path]:
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    assert pdfs, f"no sample PDFs found in {SAMPLES}"
    return pdfs


@pytest.fixture
def invoice_pdf() -> Path:
    return SAMPLES / "90374749.pdf"


def make_link(conn, **overrides) -> str:
    """Insert a link row with sensible defaults, overridable per test."""
    kwargs = {
        "storage_ref": "ref.bin",
        "filename": "doc.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1234,
        "sha256": "0" * 64,
        "expires_at": None,
        "max_downloads": None,
        "label": None,
    }
    kwargs.update(overrides)
    return db.create_link(conn, **kwargs)
