"""Helper invoked by start.cmd. Not part of the running app.

Subcommands:
  bootstrap              create .env on first run, with a generated admin token
  summary <port>         print how to open the app, and what still needs setting up
  openwhenready <port>   wait until the app answers, then open it in the browser
"""

from __future__ import annotations

import re
import secrets
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"

PLACEHOLDER_TOKENS = ("change-me", "dev-admin-token-change-me", "")


def read_env() -> dict[str, str]:
    if not ENV.exists():
        return {}
    out: dict[str, str] = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def bootstrap() -> None:
    if ENV.exists():
        print("[3/4] .env found - leaving your settings untouched.")
        return
    token = secrets.token_urlsafe(32)
    text = EXAMPLE.read_text(encoding="utf-8")
    text = re.sub(r"^ADMIN_TOKEN=.*$", f"ADMIN_TOKEN={token}", text, flags=re.M)
    ENV.write_text(text, encoding="utf-8")
    print("[3/4] Created .env with a freshly generated admin token.")


def summary(port: str) -> None:
    env = read_env()
    token = env.get("ADMIN_TOKEN", "")
    secret_file = ROOT / env.get("GOOGLE_CLIENT_SECRET_FILE", "client_secret.json")

    print()
    print(f"  App              :  http://localhost:{port}/admin")
    print(f"  Admin token      :  {token or '(missing)'}")
    print()

    if token in PLACEHOLDER_TOKENS:
        print("  [!] ADMIN_TOKEN is not set to a real value. Edit .env.")
    if not secret_file.exists():
        print(f"  [!] Google Drive is not set up yet: {secret_file.name} is missing.")
        print("      The app opens, but cannot create QR codes until it is.")
        print("      See docs/setup-guide.md, section 3.")
        print()


def open_when_ready(port: str, timeout: float = 30.0) -> None:
    url = f"http://localhost:{port}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", timeout=2) as resp:
                if resp.status == 200:
                    webbrowser.open(f"{url}/admin")
                    return
        except OSError:
            pass
        time.sleep(0.5)
    # Silent failure is fine: start.cmd already printed the address to open by hand.


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    port = sys.argv[2] if len(sys.argv) > 2 else "8000"
    if cmd == "bootstrap":
        bootstrap()
    elif cmd == "summary":
        summary(port)
    elif cmd == "openwhenready":
        open_when_ready(port)
    else:
        print(__doc__)
        sys.exit(1)
