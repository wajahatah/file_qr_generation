# Spec — Run the App in Docker (Phase 1c)

- **Status:** APPROVED 2026-09-28 — IMPLEMENTED
- **Author:** Claude (Opus 5.5), on behalf of Wajahat Ahmed
- **Date:** 2026-09-28
- **Builds on:** [spec-admin-ui.md](spec-admin-ui.md) (approved, implemented)
- **Goal, in the user's words:** "I just have to run the docker image when I want to
  generate the QR."

---

## 1. Summary

Package the app as a Docker image, started with one command or one double-click.
Docker becomes **a second way to run the app, alongside `start.cmd`, not a
replacement**.

Five things work differently inside a container. Each needs a deliberate change, and
one of them silently gives wrong dates if missed (§3.3).

---

## 2. State BEFORE this change

- The app runs natively on Windows via `start.cmd`, which needs Python on the laptop.
- The Google sign-in token is kept in **Windows Credential Manager**.
- Google sign-in opens a temporary local web server on a **random port** and opens the
  browser itself.
- Time limits use the **laptop's time zone**, read from Windows.
- The server binds to `127.0.0.1`.
- No Dockerfile, no compose file.

On this machine: the Docker CLI is installed (29.1.3) and the Docker Desktop installer
is present, but the Docker engine is **not running**.

---

## 3. What does not carry over — and the fix for each

### 3.1 Windows Credential Manager does not exist in a Linux container

`keyring` has no backend there. The Google token needs somewhere else to live.

**Fix:** a small `TokenStore` interface with two implementations:

| | Native (`start.cmd`) | Docker |
|---|---|---|
| Store | Windows Credential Manager — **unchanged** | File `/data/google-token.json` in the mounted data folder |
| Protection | Encrypted by Windows per user | File mode `0600`, owned by the container's non-root user; written atomically |

**Honest trade-off:** in Docker the token sits in a file in the app's `data` folder,
less protected than Credential Manager. Anyone who can read that folder can use the
token — but only with `drive.file` permission, i.e. only on files this app uploaded.
The folder is gitignored. Encrypting the file was considered and rejected: the key
would have to sit next to it for the app to start unattended, which adds complexity
and no real protection.

### 3.2 Google sign-in cannot open a browser or use a random port

Inside the container there is no browser, and a random port is not reachable from the
laptop. Google's redirect back after sign-in would go nowhere.

**Fix:**
- The sign-in helper listens on a **fixed port (8766)** bound to `0.0.0.0` inside the
  container, published to the laptop's `127.0.0.1:8766` only.
- Instead of trying to open a browser, the app captures the Google sign-in address and
  the page opens it in a new tab ("Continue to Google"). This uses the sign-in
  library's own supported hooks (`bind_addr`, `browser`), not a reimplementation.
- Native mode keeps opening the browser directly — **unchanged**.

### 3.3 The container's clock is UTC — limits would end at the wrong time

The app counts a limit as a calendar day **in local time**. A container defaults to
UTC. On a laptop in Pakistan (UTC+5), "until 5 October" would really end at
**4:59 AM on 6 October**, and between midnight and 5 AM the app would think it is still
yesterday. Nothing would visibly fail — the dates would just be quietly wrong.

**Fix:**
- The image includes the time-zone database; `TZ` is set in `.env`
  (e.g. `TZ=Asia/Karachi`, `TZ=Asia/Riyadh`).
- The app shows the zone it is using in **Settings**.
- If the zone is UTC, the app shows a warning banner: *"The app's time zone is UTC.
  If this is not your time zone, set TZ in the .env file — time limits otherwise end
  at the wrong hour."*

### 3.4 The server must listen on `0.0.0.0` inside the container

Otherwise Docker cannot forward the laptop's traffic to it.

**Fix, keeping the same protection as today:** the ports are published to the
laptop's **`127.0.0.1` only** (`127.0.0.1:8000:8000`). Nothing on the network can
reach the app — same as `start.cmd`. The Host-header check (`localhost`,
`127.0.0.1`) is unchanged.

### 3.5 "Run it only when I need a QR" makes limits run over more often

Expired QR codes are removed only while the app runs (existing behaviour, spec-admin-ui
§5). Starting the container only to make a QR code means expired ones stay live until
the next time.

**Recommendation:** run the container **in the background, starting automatically**
(`restart: unless-stopped`). Then it runs whenever Docker Desktop runs — which is
whenever the laptop is on, if Docker Desktop is set to start at login — with no black
window to keep open. This is the one clear advantage Docker has over `start.cmd` here.
Both modes are supported; see open question 2.

---

## 4. State AFTER this change

```
file_qr\
├── Dockerfile
├── compose.yaml
├── .dockerignore
├── docker-start.cmd        ← double-click: start (or reuse) the app, open the browser
├── docker-stop.cmd         ← double-click: stop it
├── client_secret.json      ← same file as today, mounted read-only
├── .env                    ← same file; adds TZ
└── data\                   ← created on first run: database + Google token
```

### Image

- Base `python:3.13-slim`; OS time-zone data installed.
- Runs as a **non-root** user.
- Only runtime files copied in (`app/`, `requirements.txt`) — no tests, samples,
  `.env`, secrets or databases (`.dockerignore`).
- `HEALTHCHECK` on `/healthz`.
- Dependencies installed from the pinned `requirements.txt` — same versions as native.

### compose.yaml

- Ports `127.0.0.1:8000:8000` (app) and `127.0.0.1:8766:8766` (Google sign-in return).
- Volume `./data:/data` — database and token survive restarts and image rebuilds.
- `client_secret.json` mounted **read-only**.
- `env_file: .env`, `TZ` passed through.
- `restart: unless-stopped` (open question 2).

### docker-start.cmd

1. Checks Docker Desktop is running; if not, says so in plain words and stops.
2. Creates `.env` with a generated admin token if missing — using Windows' own
   cryptographic generator, **no Python needed on the laptop**. Asks for the time zone
   once, with the laptop's current one suggested.
3. `docker compose up -d --build`, waits for `/healthz`, opens the browser, prints the
   admin token.

### Settings added

| Setting | Native default | Docker value |
|---|---|---|
| `TOKEN_STORE` | `keyring` | `file` |
| `TOKEN_FILE` | — | `/data/google-token.json` |
| `OAUTH_REDIRECT_PORT` | `0` (random) | `8766` |
| `OAUTH_BIND_ADDRESS` | `localhost` | `0.0.0.0` |
| `OAUTH_OPEN_BROWSER` | `true` | `false` (the page opens the captured link) |
| `TZ` | Windows' zone | required, from `.env` |

Native defaults are exactly today's behaviour. **`start.cmd` users see no change.**

---

## 5. Changes by file

| File | Change |
|---|---|
| `app/tokens.py` | **New.** `TokenStore` protocol; `KeyringStore` (today's code, moved); `FileStore`. |
| `app/drive.py` | Use `TokenStore`; sign-in port, bind address and browser-capture configurable; expose the captured sign-in address in `status()`. |
| `app/config.py` | Settings in §4. |
| `app/main.py` | Build the right `TokenStore`; add time zone and sign-in address to `/api/status`. |
| `app/static/admin.js`, `app/templates/admin.html` | "Continue to Google" link while signing in; time zone in Settings; UTC warning banner. |
| `Dockerfile`, `compose.yaml`, `.dockerignore` | **New.** |
| `docker-start.cmd`, `docker-stop.cmd` | **New.** CRLF, per `.gitattributes`. |
| `.gitignore` | Add `data/`. |
| `tests/` | See §7. |
| Docs | `HOW-TO-RUN.md` gains a short "Run with Docker" section; setup guide gains a Docker chapter; technical docs and README updated. |

---

## 6. Security review

| Risk | Mitigation |
|---|---|
| App reachable from the network | Ports published to `127.0.0.1` only; Host check unchanged. |
| Google token in a file | `0600`, non-root owner, gitignored `data/`, `drive.file` scope limits damage. Stated in the docs. |
| Secrets baked into the image | `.dockerignore` excludes `.env`, `client_secret.json`, `data/`, `*.db`; a test checks the build context. |
| Sign-in port always published | Nothing listens on it except during a sign-in (5-minute window); loopback only. |
| Container runs as root | Non-root user. |
| Wrong time zone | UTC warning banner; zone shown in Settings. |

---

## 7. Test plan

Changes `drive.py` and `main.py`, shared by both run modes, so per Rule 6 this is
**major**: full suite, a literal run of both modes, and a check that native is
unchanged.

**Automated (offline):**
- `FileStore`: round trip, `0600` permissions, atomic replace, delete, missing file.
- `KeyringStore`: today's behaviour, moved without change.
- Sign-in: fixed port and `0.0.0.0` passed through in Docker mode; captured address
  appears in status; native mode still opens the browser and uses a random port.
- Time zone reported in status; UTC banner shown only for UTC.
- `compose.yaml` publishes to `127.0.0.1` only, mounts the secret read-only, has a
  healthcheck; `Dockerfile` uses a non-root user and installs time-zone data;
  `.dockerignore` excludes every secret.
- **All 223 existing tests pass unmodified.**

**Real Docker run** (needs Docker Desktop started — I will ask first):
- Image builds; container becomes healthy.
- `localhost:8000` works; the laptop's network address does **not**.
- Sign in; issue a QR against the stand-in Drive; **stop and restart the container —
  links, settings and sign-in survive**.
- `TZ` set → correct local dates; unset → UTC banner.
- `docker-start.cmd` from a clean folder creates `.env` without Python.

**Native regression:** `start.cmd` run end-to-end as before.

**Needs your Google account (together):** Google sign-in through the container's
port 8766.

---

## 8. Out of scope

Running on a server or in the cloud · HTTPS · multiple users · publishing the image to
a registry · an Android/iOS app.

---

## 9. Open questions

1. **Docker Desktop licence.** Free for personal use and small businesses; a paid
   subscription is required at a company with **more than 250 employees or more than
   $10M annual revenue**. Whose laptop and company will this run on? If a large
   company: buy a licence, or use a free alternative that provides the same `docker`
   commands (e.g. Rancher Desktop) — the files in this spec work unchanged with it.
2. **Run mode.** (a) **Always on in the background** — starts with Docker Desktop,
   expired QR codes removed whenever the laptop is on. *(Recommended.)* (b) **Only when
   needed** — start it to make a QR, stop it after; expired QR codes run over until
   the next start.
3. **Time zone.** Which one should the app use — where the laptop is? This machine is
   on UTC+5 (e.g. `Asia/Karachi`). If the person issuing quotations is in Saudi Arabia,
   `Asia/Riyadh`.
4. **Keep `start.cmd` too?** *(Recommended: yes.)* Docker Desktop is a large install
   (WSL 2, a few GB, ~2 GB RAM while running); `start.cmd` needs only Python.

---

## 10. Approval

- [x] Approved by Wajahat — 2026-09-28, with these answers:
  1. **Licence:** personal, non-commercial use — Docker Desktop is free.
  2. **Run mode:** always on, in the background (`restart: unless-stopped`).
  3. **Time zone:** the user is in Asia/Karachi now and will also run it in Riyadh, and
     asked whether the zone can be updated when building the image. **Decision: set at
     start time, not build time** — a zone baked into the image would need a rebuild
     for every trip. §3.3 is revised accordingly (below).
  4. **`start.cmd`:** kept unchanged.

### §3.3 revised — time zone follows the laptop

Precedence, highest first:

1. `TZ` in `.env`, if set — an explicit override.
2. **The laptop's own Windows time zone**, read by `docker-start.cmd` every time it
   runs and passed in as `HOST_WINDOWS_TZ`; translated to the IANA name inside the
   container with `tzlocal`'s CLDR table (e.g. *Pakistan Standard Time* →
   `Asia/Karachi`, *Arab Standard Time* → `Asia/Riyadh`).
3. UTC, with the warning banner.

Travelling to Riyadh therefore needs no rebuild: with the laptop's clock on Riyadh
time, running `docker-start.cmd` switches the app.

**Gap and its safety net:** in always-on mode Docker restarts the container at login
*without* `docker-start.cmd`, keeping the zone it was created with. The page compares
the browser's current UTC offset (the laptop's real zone) with the app's; if they
differ it shows: *"Your laptop is on UTC+3 but the app is using UTC+5 — run
docker-start.cmd to switch."* Comparing offsets rather than names avoids false alarms
from zone aliases.

### Implementation notes (post-build)

Built as specced, with §3.3 as revised above. Deviations and findings:

1. **Named Docker volume instead of a `./data` folder.** Bind mounts of Windows folders
   into Linux containers do not honour POSIX permissions, so the token file could not
   be made 0600 there. A named volume gives real Linux permissions and keeps the token
   out of the project folder. Verified: 0600, owned by the non-root `app` user.
2. **The UTC warning became a general mismatch warning.** Rather than warn only when
   the zone is UTC, the page compares the browser's UTC offset (the laptop's real zone)
   with the app's. This covers the UTC default, a stale zone after travel, and never
   nags someone who genuinely lives in UTC.
3. **`compose.yaml` passes named variables only, never `env_file: .env`** — the native
   `.env` would have moved the database out of the volume. Pinned by a test.
4. **Found in the real launcher test: health wait must use `127.0.0.1`.** `localhost`
   tries IPv6 first and Docker Desktop takes ~2.1 s to reject it, longer than each
   attempt's timeout, so `docker-start.cmd` always reported failure. Fixed; regression
   test added.
5. **Found in the real container: glibc names an unset zone "Universal".** Shown as
   "UTC". Test added.
6. **`/api/status` gained fields** (`drive.sign_in_url`, `run_mode`, `time_zone`). One
   existing test compared the `drive` object exactly and was updated for the additive
   field — the only existing test changed.
7. **`tzlocal` added** for the Windows → IANA zone-name table.
8. Test-harness note, not an app issue: Git Bash does not pass a `TZ` variable to
   Windows programs; the override was verified from `cmd.exe` and through an env file,
   the ways it is really used.

**Verified with a dummy Google key:** image contents and non-root user; zone from the
laptop (Karachi), switched to Riyadh without rebuild, `.env` override, UTC default;
not reachable from the LAN address on either port; Host check; token file 0600; the
sign-in link and its return through port 8766; data kept across restart, `down`/`up`
and rebuild; `docker-start.cmd` (missing key, first run, existing `.env`) and
`docker-stop.cmd`. **Native regression:** unchanged behaviour confirmed.

**Not yet verified:** Google sign-in inside Docker with the real account.

