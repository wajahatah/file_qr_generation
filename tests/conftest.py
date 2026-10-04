"""Shared fixtures.

Every test runs against a throwaway SQLite file and an in-memory FakeDrive. Nothing
touches the network or a Google account, so the whole suite runs offline.

Time zone: tests use a fixed UTC+03:00 (the laptop's zone in Riyadh; no daylight
saving), so results do not depend on the machine running them.
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings
from app.main import app
from tests.fakes import FakeDrive

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
TZ = timezone(timedelta(hours=3))

ADMIN_TOKEN = "test-admin-token-0123456789abcdef"
AUTH = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("ALLOWED_HOSTS", '["localhost", "127.0.0.1", "testserver"]')
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET_FILE", str(tmp_path / "client_secret.json"))
    monkeypatch.setenv("SWEEP_INTERVAL_MINUTES", "60")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def drive() -> FakeDrive:
    return FakeDrive()


@pytest.fixture
def client(env, drive):
    app.state.drive_override = drive
    app.state.tz = TZ
    try:
        with TestClient(app) as c:  # `with` runs startup: schema, Drive, first sweep
            yield c
    finally:
        del app.state.drive_override
        del app.state.tz


@pytest.fixture
def session(client):
    """A client signed in through the login page, as the app is used in a browser."""
    r = client.post(
        "/admin/login", data={"token": ADMIN_TOKEN}, headers=ORIGIN, follow_redirects=False
    )
    assert r.status_code == 303, r.text
    client.headers.update(ORIGIN)
    return client


@pytest.fixture
def conn(env) -> sqlite3.Connection:
    db.init_db(env.db_path)
    c = db.connect(env.db_path)
    yield c
    c.close()


@pytest.fixture
def sample_pdfs() -> list[Path]:
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    assert len(pdfs) == 4, f"expected 4 sample PDFs in {SAMPLES}"
    return pdfs


@pytest.fixture
def invoice_pdf() -> Path:
    return SAMPLES / "90374749.pdf"


def upload(client, path: Path, *, headers=None, **form):
    """POST a PDF to /api/links. Defaults to a 7-day preset and bearer auth."""
    if "preset_days" not in form and "until" not in form:
        form["preset_days"] = 7
    with open(path, "rb") as fh:
        return client.post(
            "/api/links",
            headers=AUTH if headers is None else headers,
            files={"file": (path.name, fh, "application/pdf")},
            data={k: str(v) for k, v in form.items()},
        )
