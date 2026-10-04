"""start.cmd and its helper."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import setup_helper  # noqa: E402

START_CMD = (ROOT / "start.cmd").read_bytes()


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(setup_helper, "ENV", path)
    monkeypatch.setattr(setup_helper, "EXAMPLE", ROOT / ".env.example")
    monkeypatch.setattr(setup_helper, "ROOT", tmp_path)
    return path


# ----------------------------------------------------------- network exposure


def test_app_listens_on_this_laptop_only():
    """Spec 8.4: nothing on the network can connect, not even the same Wi-Fi."""
    text = START_CMD.decode("utf-8")
    assert re.search(r"uvicorn app\.main:app --host 127\.0\.0\.1 ", text)
    assert "0.0.0.0" not in text


def test_lan_mode_is_gone():
    text = START_CMD.decode("utf-8")
    assert "LANMODE" not in text and '"lan"' not in text.lower()
    assert "lanip" not in text and "baseurl" not in text


def test_start_cmd_has_windows_line_endings():
    assert START_CMD.count(b"\r\n") == START_CMD.count(b"\n"), "bare LF breaks cmd.exe blocks"


def test_gitattributes_keeps_cmd_files_crlf():
    assert "*.cmd text eol=crlf" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


def test_launcher_checks_for_the_google_libraries():
    text = START_CMD.decode("utf-8")
    for mod in ("google_auth_oauthlib", "keyring", "googleapiclient"):
        assert mod in text


# ------------------------------------------------------------------ bootstrap


def test_bootstrap_generates_a_strong_token_and_never_clobbers(env_file):
    setup_helper.bootstrap()
    first = env_file.read_text(encoding="utf-8")
    token = re.search(r"^ADMIN_TOKEN=(.+)$", first, re.M).group(1)
    assert len(token) >= 32 and token not in setup_helper.PLACEHOLDER_TOKENS

    env_file.write_text(first + "\nCUSTOM=kept\n", encoding="utf-8")
    setup_helper.bootstrap()
    assert "CUSTOM=kept" in env_file.read_text(encoding="utf-8")


def test_env_example_has_no_laptop_serving_settings():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    for gone in ("BASE_URL", "STORAGE_BACKEND", "DRIVE_FOLDER_ID", "SERVICE_ACCOUNT"):
        assert gone not in text


def test_summary_warns_when_google_is_not_set_up(env_file, capsys):
    env_file.write_text("ADMIN_TOKEN=abcdefghijklmnopqrstuvwxyz0123456789\n", encoding="utf-8")
    setup_helper.summary("8000")
    out = capsys.readouterr().out
    assert "http://localhost:8000/admin" in out
    assert "client_secret.json is missing" in out


def test_summary_is_quiet_when_everything_is_set_up(env_file, capsys):
    env_file.write_text("ADMIN_TOKEN=abcdefghijklmnopqrstuvwxyz0123456789\n", encoding="utf-8")
    (env_file.parent / "client_secret.json").write_text("{}", encoding="utf-8")
    setup_helper.summary("8000")
    assert "[!]" not in capsys.readouterr().out


def test_read_env_ignores_comments_and_blanks(env_file):
    env_file.write_text("# c\n\nADMIN_TOKEN = abc \nMALFORMED\n", encoding="utf-8")
    assert setup_helper.read_env() == {"ADMIN_TOKEN": "abc"}


# ------------------------------------------------------------ opening the app


def test_browser_opens_once_the_app_answers():
    resp = mock.MagicMock(status=200)
    resp.__enter__.return_value = resp
    with mock.patch("urllib.request.urlopen", side_effect=[OSError("not yet"), resp]), \
         mock.patch("webbrowser.open") as open_, mock.patch("time.sleep"):
        setup_helper.open_when_ready("8123")
    open_.assert_called_once_with("http://localhost:8123/admin")


def test_browser_is_not_opened_if_the_app_never_starts():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")), \
         mock.patch("webbrowser.open") as open_, mock.patch("time.sleep"):
        setup_helper.open_when_ready("8123", timeout=0.01)
    open_.assert_not_called()
