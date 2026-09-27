"""Helper invoked by start.cmd. Not part of the running service.

Subcommands:
  bootstrap   create .env from .env.example on first run, with a generated admin token
  baseurl     print the BASE_URL this run should use (see resolve_base_url)
  summary     print the effective configuration, with warnings for bad combinations
  lanip       print this machine's LAN IP (for testing a scan from a real phone)
"""

from __future__ import annotations

import re
import secrets
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"


def lan_ip() -> str:
    """Best-effort LAN address. No packets are sent; connect() on UDP just picks a route."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def read_env() -> dict[str, str]:
    if not ENV.exists():
        return {}
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def bootstrap(port: str) -> None:
    if ENV.exists():
        print("[3/4] .env found - leaving your settings untouched.")
        return

    token = secrets.token_urlsafe(32)
    text = EXAMPLE.read_text(encoding="utf-8")
    text = re.sub(r"^BASE_URL=.*$", f"BASE_URL=http://localhost:{port}", text, flags=re.M)
    text = re.sub(r"^ADMIN_TOKEN=.*$", f"ADMIN_TOKEN={token}", text, flags=re.M)
    ENV.write_text(text, encoding="utf-8")

    print("[3/4] Created .env with a freshly generated admin token.")
    print("      Edit .env to change storage backend, expiry, or the public URL.")


LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


def is_local(url: str) -> bool:
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    return host in LOCAL_HOSTS or re.fullmatch(r"(10|192\.168|172\.(1[6-9]|2\d|3[01]))\..*", host) is not None


def resolve_base_url(port: str, lan: bool) -> str:
    """Decide the BASE_URL for this run.

    BASE_URL is baked into every QR at generation time, so it must match the origin
    the server is actually reachable at -- otherwise the codes point nowhere.

    A real (non-local) BASE_URL in .env is a deliberate production setting and always
    wins. A local one is treated as a dev default and is re-derived from the port
    actually being used, which stops a QR from encoding a stale port after someone
    starts the server on a different one.
    """
    configured = read_env().get("BASE_URL", "")
    if configured and not is_local(configured):
        return configured
    host = lan_ip() if lan else "localhost"
    return f"http://{host}:{port}"


def summary(base_url: str) -> None:
    env = read_env()
    backend = env.get("STORAGE_BACKEND", "local")
    token = env.get("ADMIN_TOKEN", "(unset)")

    print()
    print("  Server URL       :  " + base_url)
    print("  API docs         :  " + base_url + "/docs")
    print("  Storage backend  :  " + backend)
    print("  Admin token      :  " + token)
    print()

    warnings = []
    if token in ("change-me", "dev-admin-token-change-me"):
        warnings.append("ADMIN_TOKEN is still the placeholder. Change it in .env.")
    if backend == "drive":
        if not env.get("DRIVE_FOLDER_ID"):
            warnings.append("STORAGE_BACKEND=drive but DRIVE_FOLDER_ID is empty.")
        key = ROOT / env.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service-account.json")
        if not key.exists():
            warnings.append(f"Service account key not found at {key}")
        if warnings:
            warnings.append("See docs/setup-guide.md section 5.")
    if base_url.startswith(("http://localhost", "http://127.")):
        warnings.append(
            "QR codes will only work on THIS machine.\n"
            "        To scan with your phone, stop and run:  start.cmd lan"
        )
    elif is_local(base_url):
        warnings.append(
            "LAN mode: QR codes work only for devices on this Wi-Fi network,\n"
            "        and stop working when this machine's IP changes."
        )

    for w in warnings:
        print("  [!] " + w)
    if warnings:
        print()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "lanip":
        print(lan_ip())
    elif cmd == "baseurl":
        port = sys.argv[2] if len(sys.argv) > 2 else "8000"
        print(resolve_base_url(port, lan=(len(sys.argv) > 3 and sys.argv[3] == "lan")))
    elif cmd == "bootstrap":
        bootstrap(sys.argv[2] if len(sys.argv) > 2 else "8000")
    elif cmd == "summary":
        summary(sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000")
    else:
        print(__doc__)
        sys.exit(1)
