"""start.cmd's BASE_URL resolution.

BASE_URL is baked into every QR at generation time. If it does not match the origin
the server is actually reachable at, the codes point nowhere -- and nothing fails
loudly, because a wrong-but-well-formed URL still renders a perfectly good QR. Hence
these tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import setup_helper  # noqa: E402


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """Point the helper at a throwaway .env."""
    path = tmp_path / ".env"
    monkeypatch.setattr(setup_helper, "ENV", path)
    return path


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:8000", True),
        ("http://127.0.0.1:8000", True),
        ("http://0.0.0.0:8000", True),
        ("http://192.168.2.106:8000", True),
        ("http://10.0.0.5", True),
        ("http://172.16.4.4", True),
        ("http://172.32.4.4", False),  # outside the private 172.16/12 range
        ("https://qr.example.com", False),
        ("https://qr.abunayyan.com.sa", False),
    ],
)
def test_is_local_classification(url: str, expected: bool) -> None:
    assert setup_helper.is_local(url) is expected


def test_a_production_base_url_is_never_overridden(env_file) -> None:
    """A real domain in .env is a deliberate setting and must survive any port arg."""
    env_file.write_text("BASE_URL=https://qr.abunayyan.com.sa\n", encoding="utf-8")
    assert setup_helper.resolve_base_url("8000", lan=False) == "https://qr.abunayyan.com.sa"
    assert setup_helper.resolve_base_url("9999", lan=True) == "https://qr.abunayyan.com.sa"


def test_a_local_base_url_follows_the_port_actually_in_use(env_file) -> None:
    """The regression this file exists for.

    Start once on port 8123 and .env records localhost:8123. Start again with no
    arguments and the server listens on 8000 -- every QR issued would encode the
    stale 8123 and resolve to nothing.
    """
    env_file.write_text("BASE_URL=http://localhost:8123\n", encoding="utf-8")
    assert setup_helper.resolve_base_url("8000", lan=False) == "http://localhost:8000"


def test_missing_env_falls_back_to_localhost(env_file) -> None:
    assert setup_helper.resolve_base_url("8000", lan=False) == "http://localhost:8000"


def test_lan_mode_uses_a_routable_address(env_file, monkeypatch) -> None:
    monkeypatch.setattr(setup_helper, "lan_ip", lambda: "192.168.2.106")
    url = setup_helper.resolve_base_url("8000", lan=True)
    assert url == "http://192.168.2.106:8000"
    assert "localhost" not in url, "a phone cannot resolve localhost to this machine"


def test_bootstrap_generates_a_strong_token_and_never_clobbers(env_file, monkeypatch) -> None:
    monkeypatch.setattr(setup_helper, "EXAMPLE", ROOT / ".env.example")

    setup_helper.bootstrap("8000")
    first = env_file.read_text(encoding="utf-8")
    token = next(l.split("=", 1)[1] for l in first.splitlines() if l.startswith("ADMIN_TOKEN="))

    assert len(token) >= 32, "generated admin token is too short"
    assert token not in ("change-me", "dev-admin-token-change-me")
    assert "BASE_URL=http://localhost:8000" in first

    # Running start.cmd again must not overwrite the operator's settings.
    env_file.write_text(first + "\nCUSTOM=kept\n", encoding="utf-8")
    setup_helper.bootstrap("8000")
    assert "CUSTOM=kept" in env_file.read_text(encoding="utf-8")


def test_helper_parses_env_ignoring_comments_and_blanks(env_file) -> None:
    env_file.write_text(
        "# a comment\n\nBASE_URL=https://x.test\n  ADMIN_TOKEN = abc \nMALFORMED\n",
        encoding="utf-8",
    )
    env = setup_helper.read_env()
    assert env["BASE_URL"] == "https://x.test"
    assert env["ADMIN_TOKEN"] == "abc"
    assert "MALFORMED" not in env
