"""The Docker packaging, checked without Docker: the properties that keep it safe.

The real build-and-run check is done separately (spec-docker section 7); these catch a
careless edit to the files before anyone builds anything.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
APP = COMPOSE["services"]["app"]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")


# ------------------------------------------------------------------ compose.yaml


def test_ports_are_published_on_the_laptop_only():
    """"8000:8000" would expose the app to the whole network."""
    for mapping in APP["ports"]:
        assert mapping.startswith("127.0.0.1:"), mapping


def test_sign_in_port_is_the_same_on_both_sides():
    """Google returns to localhost:8766; Docker must forward that exact port."""
    assert "127.0.0.1:8766:8766" in APP["ports"]


def test_native_env_file_is_not_loaded_wholesale():
    """env_file: .env would bring in DB_PATH=./file_qr.db, moving the database out of
    the volume -- every rebuild would then silently lose all issued QR codes."""
    assert "env_file" not in APP
    for key in APP["environment"]:
        assert key not in ("DB_PATH", "GOOGLE_CLIENT_SECRET_FILE", "TOKEN_FILE", "TOKEN_STORE")


def test_time_zone_follows_the_laptop():
    assert "HOST_WINDOWS_TZ" in APP["environment"] and "TZ" in APP["environment"]


def test_data_lives_in_a_named_volume():
    assert "qr-data:/data" in APP["volumes"]
    assert "qr-data" in COMPOSE["volumes"]


def test_google_key_is_a_secret_not_baked_or_bind_mounted_writable():
    assert APP["secrets"] == ["client_secret"]
    assert COMPOSE["secrets"]["client_secret"]["file"] == "./client_secret.json"


def test_always_on():
    assert APP["restart"] == "unless-stopped"


# ------------------------------------------------------------------- Dockerfile


def test_runs_as_a_non_root_user():
    users = re.findall(r"^USER\s+(\S+)", DOCKERFILE, re.M)
    assert users and users[-1] not in ("root", "0")


def test_image_has_the_time_zone_database():
    assert re.search(r"apt-get install[^\n]*\btzdata\b", DOCKERFILE)


def test_docker_mode_settings():
    for setting in ("RUN_MODE=docker", "TOKEN_STORE=file", "DB_PATH=/data/",
                    "TOKEN_FILE=/data/", "OAUTH_REDIRECT_PORT=8766",
                    "OAUTH_BIND_ADDRESS=0.0.0.0", "OAUTH_OPEN_BROWSER=false",
                    "GOOGLE_CLIENT_SECRET_FILE=/run/secrets/client_secret"):
        assert setting in DOCKERFILE, setting


def test_healthcheck_and_listen_address():
    assert "HEALTHCHECK" in DOCKERFILE and "/healthz" in DOCKERFILE
    assert '"--host", "0.0.0.0"' in DOCKERFILE


def test_dependencies_come_from_the_pinned_requirements():
    assert "pip install -r requirements.txt" in DOCKERFILE
    assert "tzlocal==" in (ROOT / "requirements.txt").read_text(encoding="utf-8")


# ----------------------------------------------------------------- .dockerignore


def test_build_context_is_an_allow_list():
    lines = [l.strip() for l in DOCKERIGNORE.splitlines() if l.strip() and not l.startswith("#")]
    assert lines[0] == "*", "start by excluding everything"
    allowed = {l[1:] for l in lines if l.startswith("!")}
    assert allowed == {"app/", "requirements.txt"}


# ---------------------------------------------------------------- launchers


@pytest.mark.parametrize("name", ["docker-start.cmd", "docker-stop.cmd"])
def test_launchers_have_windows_line_endings(name):
    data = (ROOT / name).read_bytes()
    assert data.count(b"\r\n") == data.count(b"\n")


def test_docker_start_needs_no_python():
    text = (ROOT / "docker-start.cmd").read_text(encoding="utf-8")
    code = "\n".join(l for l in text.splitlines() if not l.strip().upper().startswith("REM"))
    assert "python" not in code.lower()
    assert "RandomNumberGenerator" in code, "token from Windows' cryptographic generator"


def test_docker_start_passes_the_laptop_time_zone():
    text = (ROOT / "docker-start.cmd").read_text(encoding="utf-8")
    assert "Get-TimeZone" in text and "HOST_WINDOWS_TZ" in text


def test_data_folder_and_secrets_are_gitignored():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("client_secret*.json", ".env", "*.db"):
        assert pattern in ignored


def test_docker_start_waits_on_ipv4_not_localhost():
    """Regression, found in the real launcher test: `localhost` tries IPv6 first, and
    Docker Desktop's forwarding takes ~2 s to reject it -- longer than each attempt's
    timeout, so waiting on localhost never succeeded."""
    text = (ROOT / "docker-start.cmd").read_text(encoding="utf-8")
    wait = next(l for l in text.splitlines() if "Invoke-WebRequest" in l)
    assert "http://127.0.0.1:" in wait and "http://localhost:" not in wait
