"""Environment-driven configuration.

Every value has a development-safe default so the service runs out of the box with
`uvicorn app.main:app`. Production overrides come from the environment or a `.env`
file; see `.env.example`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # The public origin the QR code points at. In production this MUST be the
    # externally reachable HTTPS origin -- a QR encoding "localhost" is useless to
    # anyone but the machine that generated it.
    base_url: str = "http://localhost:8000"

    # "local" keeps files on disk (default, used by the test suite -- no network).
    # "drive" stores them in a private Google Drive folder via a service account.
    storage_backend: Literal["local", "drive"] = "local"
    storage_dir: Path = PROJECT_ROOT / "storage"

    # Only read when storage_backend == "drive".
    drive_folder_id: str = ""
    google_service_account_file: Path = PROJECT_ROOT / "service-account.json"
    # Least privilege by default: drive.file limits the app to files it created.
    # Switch to the full "drive" scope only if uploads fail with a 404 on the folder
    # -- see docs/setup-guide.md, "If uploads fail".
    drive_scope: str = "https://www.googleapis.com/auth/drive.file"

    db_path: Path = PROJECT_ROOT / "file_qr.db"

    # Static bearer token guarding every /api/ route. Phase 1 is single-operator;
    # see docs/planning/spec-qr-file-share.md section 8, question 4.
    admin_token: str = "dev-admin-token-change-me"

    default_expiry_days: int | None = 30
    max_upload_bytes: int = 25 * 1024 * 1024
    log_retention_days: int = 90

    @property
    def download_url_prefix(self) -> str:
        return f"{self.base_url.rstrip('/')}/d/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
