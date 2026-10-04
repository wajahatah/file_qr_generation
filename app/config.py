"""Environment-driven configuration.

Every value has a safe default so the app runs out of the box via start.cmd.
Overrides come from the environment or a `.env` file; see `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Password for the app and the /api/ routes. start.cmd generates a strong one.
    admin_token: str = "dev-admin-token-change-me"
    admin_session_hours: int = 12

    db_path: Path = PROJECT_ROOT / "file_qr.db"

    # OAuth client of type "Desktop app", downloaded from Google Cloud.
    # See docs/setup-guide.md section 3.
    google_client_secret_file: Path = PROJECT_ROOT / "client_secret.json"

    max_upload_bytes: int = 25 * 1024 * 1024

    # How often expired files are removed from Drive while the app runs.
    sweep_interval_minutes: int = 10

    # Requests whose Host header is not in this list are refused. This is what stops
    # a malicious website from reaching the app via DNS rebinding (spec section 10).
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]

    # --- run mode --------------------------------------------------------------
    # Defaults are the native start.cmd behaviour. compose.yaml sets the Docker values
    # (spec-docker section 4). Nothing here changes how start.cmd works.

    # Only used to word hints on the page ("run docker-start.cmd" vs "run start.cmd").
    run_mode: Literal["native", "docker"] = "native"

    # Where the Google sign-in token lives: Windows Credential Manager, or a file in
    # the Docker data volume (a Linux container has no Credential Manager).
    token_store: Literal["keyring", "file"] = "keyring"
    token_file: Path = PROJECT_ROOT / "data" / "google-token.json"

    # Google sign-in: 0 = any free port. Docker needs a fixed, published port, a bind
    # to all interfaces inside the container, and the page to open the link instead
    # of the app (there is no browser in a container).
    oauth_redirect_port: int = 0
    oauth_bind_address: str | None = None
    oauth_open_browser: bool = True

    # Time zone for time limits (app/timezone.py). TZ overrides; HOST_WINDOWS_TZ is the
    # laptop's Windows zone, passed in by docker-start.cmd. Ignored when running
    # natively on Windows, which already uses Windows' zone.
    tz: str | None = None
    host_windows_tz: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
