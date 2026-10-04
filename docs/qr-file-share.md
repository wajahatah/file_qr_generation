# QR File Share — Technical Documentation

A laptop app that issues QR codes for PDFs delivered from the user's Google Drive,
with a time limit on each.

- User-facing setup and usage: [setup-guide.md](setup-guide.md)
- Design and decisions: [planning/spec-admin-ui.md](planning/spec-admin-ui.md) (current),
  [planning/spec-docker.md](planning/spec-docker.md) (Docker),
  [planning/spec-docker-kit.md](planning/spec-docker-kit.md) (portable kit),
  [planning/spec-qr-file-share.md](planning/spec-qr-file-share.md) (phase 1, superseded in part)
- The phase-1 system that served files from the laptop is preserved at git tag
  `phase-1-laptop-delivery`.

---

## 1. Architecture

```
LAPTOP — FastAPI on 127.0.0.1 only                  GOOGLE DRIVE (user's own account)
┌───────────────────────────────────────┐
│ /admin  pages (Jinja + static JS/CSS) │  upload → record → share
│ /api    JSON, bearer or session auth  │ ──────────────────────────▶  "QR File Share" folder
│ sweep   every 10 min + at startup     │  trash expired / ended       file: anyone-with-link, reader
│ SQLite  links · sessions · settings   │ ──────────────────────────▶
└───────────────────────────────────────┘                                   ▲
                                                                            │ opens Drive link
                                              CUSTOMER'S PHONE ── scans QR ─┘ (laptop may be off)
```

The QR code encodes the Drive `webViewLink` directly. Nothing is ever served to a
customer by the laptop.

| Module | Responsibility |
|---|---|
| `app/main.py` | App, middleware (Host check, security headers, caching), error mapping, `/api/*`, sweep scheduler. |
| `app/admin.py` | Pages: login, logout, main screen, print view, `/sw.js`. |
| `app/deps.py` | Shared dependencies; `require_admin`, the single auth gate. |
| `app/service.py` | Business rules: issue, change limit, end, reactivate, sweep. |
| `app/limits.py` | Pure date logic and the words shown to the user. |
| `app/drive.py` | `DriveClient` protocol and the real `GoogleDrive` client. |
| `app/db.py` | SQLite schema and queries. |
| `app/qr.py` | QR rendering. |
| `app/config.py` | Environment-driven settings. |
| `app/tokens.py` | `TokenStore`: Windows Credential Manager (native) or a 0600 file (Docker). |
| `app/timezone.py` | Which zone limits use: `TZ`, else the laptop's Windows zone, else system. |
| `tools/setup_helper.py` | Used by `start.cmd`: `.env` bootstrap, summary, open browser. |

## 2. Time limits (`app/limits.py`)

A limit is a **calendar day in the laptop's local time**. Stored as the instant it
runs out — local midnight at the start of the following day — in UTC. A link is live
while `now < expires_at`.

- Presets: 1, 3, 7, 30 days, counted from today's local date.
- Picked date: today to today + 365.
- Extend: +7 or +30 days, counted from the later of the current last day and today,
  so extending an already-expired link gives a real N days.
- `tz=None` means the OS local zone. `expiry_instant` builds a *naive* local midnight
  and calls `.astimezone()`, which applies the OS's rules for that date — daylight
  saving is handled correctly (tested with `Europe/London` across 25 Oct 2026).
- Every sentence the user reads ("until Mon 5 Oct 2026, 11:59 PM (7 days)") comes from
  the server. The page does no date arithmetic, so the preview and the stored value
  cannot disagree. Preview and save share `service.resolve_change`.
- `links.expires_at` is `NOT NULL`: "every QR has a limit" is enforced by the
  database, not only the UI.

## 3. Enforcing the limit

Google Drive cannot expire an "anyone with the link" share (the Drive API allows
`expirationTime` only on user and group permissions). The app enforces it:

- `service.sweep` trashes every link with `removed_at IS NULL AND (expires_at <= now
  OR revoked_at IS NOT NULL)`.
- It runs at startup — which catches limits that ran out while the laptop was off —
  then every `SWEEP_INTERVAL_MINUTES` (default 10), and on demand via
  `POST /api/maintenance/sweep`.
- A link is marked removed only after Drive confirms. Failures stay due and retry.
  A file already deleted by hand counts as removed.
- If Drive is not connected, the sweep does nothing and `/api/status` reports how many
  links are waiting; the UI shows a warning.

**Known limitation:** a limit reached while the laptop is off is enforced late — at
the next start. Closing this needs something always-on; spec §15 Q1 records the
Apps Script option and why it was deferred.

### Revoke and reactivate

- **End now** sets `revoked_at` and trashes the file. Final: an ended link cannot be
  reactivated.
- **Reactivate** (expired, not ended, within 30 days of removal — Drive empties its
  trash at 30 days) un-trashes the same file. Same file ID, same URL: the QR code
  already in a customer's hands works again.
- Trash rather than removing the sharing permission: without the permission, a
  scanner sees Drive's "Request access" button, and every press emails the owner.

## 4. The orphan-safety rule (`service.issue_link`)

A file public on Drive with no database row would have no limit anyone enforces — a
permanent public link. Issuing is therefore ordered:

1. Upload (private).
2. Insert the row, committed.
3. Share as anyone-with-link reader.

Failure handling:

| Fails at | Result |
|---|---|
| 1 | Nothing created. |
| 2 | File trashed (it was never public). |
| 3 | The share may have taken effect at Google even though an error came back. The row is marked revoked, then the file trashed. If trashing also fails, the revoked row stays and the sweep retries until Drive confirms. |

`tests/test_service.py::test_share_that_took_effect_while_drive_went_away_is_still_removed_later`
covers the worst case.

## 5. Google Drive (`app/drive.py`)

- **Sign-in:** OAuth desktop flow, `InstalledAppFlow.run_local_server(port=0)`, in a
  background thread; the UI polls `/api/status`. 5-minute timeout. `prompt=consent`
  so a refresh token is always returned, including on reconnect.
- **Scope:** `drive.file` only — access to files the app created. Non-sensitive:
  no Google verification needed. Consequence: the app cannot write into a folder the
  user made, so it creates its own, **QR File Share**, found again by name.
- **Credential:** only the refresh token is kept, in Windows Credential Manager
  (`keyring`, service `qr-file-share`). Client ID and secret are read from
  `client_secret.json`. No access token is stored anywhere.
- **Disconnect:** revokes the token at Google (best effort), then deletes it locally.
- **Thread safety:** Google API service objects are not thread-safe, and routes and
  the sweep both call Drive from worker threads. A lock serialises every Drive call.
- **Errors** are translated for the user: 404 → `DriveNotFound`; expired or revoked
  sign-in → `DriveNotConnected` ("Reconnect Google Drive"); network → "Check the
  internet connection".
- **Consent screen stays in "Testing"**, with the user added as a test user. Publishing
  an External app to "In production" now requires a home page, privacy policy and an
  authorised domain the user owns (Google does not accept GitHub Pages), which is
  out of proportion for a single-user app. Consequence: Google expires the refresh
  token after 7 days; the next Drive call raises `DriveNotConnected` and the UI asks
  the user to reconnect. Until they do, the sweep cannot remove expired files and
  `/api/status` reports how many are waiting. Workspace accounts can use an
  *Internal* consent screen, which has neither limit.

## 6. Security

The server binds to `127.0.0.1`. But any web page open in the same browser can make
the browser send requests to `localhost`, so the app still defends itself:

| Threat | Defence |
|---|---|
| Other users / processes on the laptop | Admin token login, 12-hour session. |
| Cross-site request forgery | Session cookie `HttpOnly`, `SameSite=Strict`; every cookie-authenticated POST must carry an `Origin` equal to its own host (`null` refused). Bearer requests exempt — a forged request cannot set `Authorization`. |
| DNS rebinding | Requests whose `Host` is not in `ALLOWED_HOSTS` (`localhost`, `127.0.0.1`) get 400. |
| Stolen database | Sessions stored as SHA-256 only. |
| Script injection | Untrusted text inserted with `textContent` only; CSP `default-src 'self'`, no inline script or style; Jinja autoescaping. Enforced by tests that scan templates and JS. |
| Clickjacking | `X-Frame-Options: DENY`, `frame-ancestors 'none'`. |
| Malicious upload | PDF checked by magic bytes, 25 MB cap; filename reduced to a base name. |
| Google token theft | Windows Credential Manager; `drive.file` limits damage to this app's own files. |
| Forwarded QR code | Accepted: the time limit is the control; End now for emergencies. |

`Referrer-Policy` is `same-origin`, **not** `no-referrer`: under `no-referrer`,
browsers send `Origin: null` on POSTs, which the CSRF check refuses — breaking
sign-in and every save. Found in the browser run; pinned by a test.

Static files are served `Cache-Control: no-cache` so an updated `admin.js` / `admin.css`
is always picked up. Also found in the browser run.

## 7. API

All `/api/*` routes need `Authorization: Bearer <ADMIN_TOKEN>` or a session cookie.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/status` | Drive state, preset list, date bounds, default, last sweep. |
| `POST` | `/api/limits/preview` | `{preset_days}` or `{until}` → last day + sentence. |
| `POST` | `/api/drive/connect` | Start Google sign-in (202; poll status). |
| `POST` | `/api/drive/disconnect` | Revoke and forget. |
| `POST` | `/api/links` | Multipart: `file`, `label?`, `preset_days` or `until`. |
| `GET` | `/api/links` | All links, newest first, with plain-words status and allowed actions. |
| `GET` | `/api/links/{id}` | One link. |
| `GET` | `/api/links/{id}/qr.png` | The QR code. |
| `POST` | `/api/links/{id}/limit/preview` | `{extend_days}` or `{until}` → sentence. |
| `POST` | `/api/links/{id}/limit` | Change the limit. |
| `POST` | `/api/links/{id}/end` | End now. Returns `removed_from_drive`. |
| `POST` | `/api/links/{id}/reactivate` | `{preset_days}` or `{until}`. |
| `GET` / `PUT` | `/api/settings` | `{default_preset_days}`. |
| `POST` | `/api/maintenance/sweep` | Run the removal sweep now. |

Errors are `{"detail": "<message for the user>"}`: 400 invalid choice, 401 not signed
in, 403 cross-origin, 404 unknown, 409 Drive not connected, 413 too large, 415 not a
PDF, 502 Drive failed.

## 8. Data model

```sql
links          (id, drive_file_id UNIQUE, drive_url, filename, size_bytes, sha256,
                label, created_at, expires_at NOT NULL, revoked_at, removed_at)
admin_sessions (id_hash PRIMARY KEY, created_at, expires_at)
settings       (key PRIMARY KEY, value)            -- default_preset_days
```

All times are UTC ISO-8601 at second precision, so string comparison is time order.
A phase-1 database (with a `token` column) found at startup is renamed to
`*.phase1.bak`, never deleted.

SQLite connections use `check_same_thread=False`. Safe only because each request and
each sweep run opens its own connection and uses it sequentially — keep it that way.

## 9. Configuration (`.env`)

| Variable | Default | |
|---|---|---|
| `ADMIN_TOKEN` | generated by `start.cmd` | App and API password. |
| `ADMIN_SESSION_HOURS` | 12 | |
| `GOOGLE_CLIENT_SECRET_FILE` | `./client_secret.json` | Desktop-app OAuth client. |
| `DB_PATH` | `./file_qr.db` | |
| `MAX_UPLOAD_BYTES` | 26214400 | 25 MB. |
| `SWEEP_INTERVAL_MINUTES` | 10 | |
| `ALLOWED_HOSTS` | `["localhost","127.0.0.1"]` | Host header allow-list. |

Docker-mode settings, set by the `Dockerfile` (native default in brackets):
`RUN_MODE=docker` [native], `TOKEN_STORE=file` [keyring],
`TOKEN_FILE=/data/google-token.json`, `DB_PATH=/data/file_qr.db`,
`GOOGLE_CLIENT_SECRET_FILE=/run/secrets/client_secret`, `OAUTH_REDIRECT_PORT=8766`
[0 = any free port], `OAUTH_BIND_ADDRESS=0.0.0.0` [localhost], `OAUTH_OPEN_BROWSER=false`
[true]. `compose.yaml` passes `ADMIN_TOKEN`, `ADMIN_SESSION_HOURS`,
`SWEEP_INTERVAL_MINUTES`, `TZ`, `HOST_WINDOWS_TZ`.

## 10. Tests

```
.venv\Scripts\python.exe -m pytest
```

310 tests, all offline, plus 1 Linux-only test run inside the container. Google Drive
is replaced by `tests/fakes.py::FakeDrive`, which
exists only in the test suite.

| File | Covers |
|---|---|
| `test_limits.py` | Presets, picked dates, the midnight boundary, local vs UTC dates, daylight saving, extend rules, every status sentence. |
| `test_service.py` | Issue order, every orphan-safety failure path, sweep, change / end / reactivate. |
| `test_api.py` | Every sample PDF → QR → decoded → exact bytes; upload validation; limits; settings; startup catch-up sweep. |
| `test_auth.py` | Sessions, cookie flags, CSRF, DNS rebinding, headers, no inline script, no HTML sinks, XSS in the print page. |
| `test_drive_google.py` | The real `GoogleDrive` client with Google mocked: credential handling, request shapes, error translation, sign-in outcomes. |
| `test_db.py` | Schema, phase-1 hand-over, sessions, settings. |
| `test_qr.py` | QR round-trip, compact size, quiet zone. |
| `test_launcher.py` | `start.cmd` binds 127.0.0.1 only, CRLF endings, `.env` bootstrap, browser opening. |
| `test_tokens.py` | File store round trip, 0600, atomic write, damaged file; keyring store. |
| `test_timezone.py` | Windows → IANA zone names, precedence, travelling, UTC naming. |
| `test_drive_signin_modes.py` | Native vs Docker sign-in: ports, bind address, link handed to the page. |
| `test_docker_files.py` | Ports on 127.0.0.1 only, no wholesale `.env`, non-root, tzdata, allow-list build context, launchers. |
| `test_kit.py` | Kit compose never builds or pulls and matches the project's on security; version naming; secret detection; CPU detection; launcher's kit branch. |

`tests/run_fake_server.py` runs the real app against `FakeDrive` for trying the UI
without a Google account (token `fake-server-token`).

### Verified vs not yet verified

| | |
|---|---|
| All logic, the API, and the UI in a real browser against the fake Drive | Verified |
| `start.cmd` first run; browser opens; not reachable from the LAN address | Verified |
| Google sign-in (native) with the user's real account | Verified — completed by the user, 2026-09-28 |
| Docker: image contents, non-root, zone switching without rebuild, 0600 token file, sign-in return path through port 8766, data kept across restart / down / rebuild, `docker-start.cmd` and `docker-stop.cmd` | Verified, with a dummy Google key |
| Real upload, real sharing and trashing | **Not yet — needs the user's Google account** |
| Google sign-in inside Docker with the real account | **Not yet** |
| Scanning a real QR code on a phone with the laptop off | **Not yet — needs the above** |
| "Install app" in Edge / Chrome | **Not yet — the test browser cannot install apps** |

## 11. Known limitations

- A limit reached while the laptop is off is enforced at the next start (§3).
- Google signs the app out weekly (consent screen in "Testing", §5). Limits reached
  while signed out are enforced once the user reconnects.
- Anyone holding a live QR code or link can open and save the PDF; it can be
  forwarded. The time limit is the control.
- No download counts or scan history: Google Drive does not report them to the app.
- One user; one admin token.
- Offline scanning is impossible: a QR code holds at most 2,953 bytes of binary data.

## 12. Running in Docker

`Dockerfile`, `compose.yaml`, `docker-start.cmd`, `docker-stop.cmd`. Design:
[planning/spec-docker.md](planning/spec-docker.md). Five things differ from native:

| | Native | Docker |
|---|---|---|
| Google token | Windows Credential Manager | `/data/google-token.json`, 0600, owned by the non-root `app` user |
| Google sign-in | Random port; the app opens the browser | Port 8766, bound `0.0.0.0` in the container, published `127.0.0.1:8766`; the link is captured through the library's own `browser` hook and the page opens it |
| Time zone | Windows' own | `TZ` from `.env`, else the laptop's Windows zone passed as `HOST_WINDOWS_TZ` and mapped with `tzlocal`'s CLDR table, else UTC |
| Listen address | `127.0.0.1` | `0.0.0.0` in the container; published on the laptop's `127.0.0.1` only |
| Data | `./file_qr.db` | Named volume `qr-file-share_qr-data` |

Points worth knowing before changing anything:

- **`compose.yaml` must not use `env_file: .env`.** The native `.env` holds
  `DB_PATH=./file_qr.db`, which would move the database out of the volume — every
  rebuild would then silently lose all issued QR codes. Only named variables are
  passed. Pinned by `test_native_env_file_is_not_loaded_wholesale`.
- **The zone is set at start, not build.** One image serves Karachi and Riyadh;
  `docker-start.cmd` recreates the container when the laptop's zone changes. In
  always-on mode Docker restarts the container at login with its old zone, so the page
  compares the browser's UTC offset with the app's and warns when they differ.
- **Health checks from Windows use `127.0.0.1`, not `localhost`.** `localhost` tries
  IPv6 first, and Docker Desktop's forwarding takes ~2 s to reject it. Found in the
  real launcher test.
- **The build context is an allow-list** (`.dockerignore`): only `app/` and
  `requirements.txt`. The built image was inspected: no `.env`, key, database or token
  anywhere in its filesystem.
- Native and Docker keep **separate** databases and Google sign-ins; use one.

## 13. Portable kit

`make-kit.cmd` → `tools/make_kit.py` produces `dist/qr-file-share-kit-<version>.zip`
(`dist/` is gitignored). Design: [planning/spec-docker-kit.md](planning/spec-docker-kit.md).

| In the kit | |
|---|---|
| `qr-file-share-image-amd64.tar`, `qr-file-share-image-arm64.tar` | One single-platform image each (`--provenance=false --sbom=false`), so `docker load` works whichever image store the target's Docker uses. |
| `compose.yaml` | Rendered from `tools/kit/compose.yaml`: `image: qr-file-share:<version>`, `pull_policy: never`, no `build`. Same project name, volume, ports and environment as the project's — pinned by `test_kit_matches_the_project_on_everything_that_matters`. |
| `docker-start.cmd`, `docker-stop.cmd`, `.env.example`, `START-HERE.md`, `VERSION` | The same launcher as the project folder. |

- **Version** = `YYYY.MM.DD-<git sha>`, plus `-dirty` from uncommitted changes.
- **One launcher.** `docker-start.cmd` builds when a `Dockerfile` is present; otherwise
  it reads `VERSION`, maps `PROCESSOR_ARCHITECTURE` (or `PROCESSOR_ARCHITEW6432`) to
  `amd64` / `arm64`, and `docker load`s that tar unless that version is already loaded.
- **Build order:** the non-native image is built and saved first, then removed; the
  native one last, so the tag left on the build laptop is runnable there.
- **Safety:** tests must pass; each tar's recorded architecture is checked; the kit
  folder and the image filesystem are scanned for `.env`, `client_secret*.json`,
  databases and tokens — any hit aborts.
- **Distribution:** a GitHub Release asset (repository files are capped at 100 MB).
- **Options:** `--arch amd64` (or `arm64`, repeatable) builds only those processor types —
  the emulated ARM build takes 15+ minutes. `--reuse-image TAG` (with one `--arch`)
  packages an already-built local image instead of building, for when Docker Hub is
  unreachable; the architecture and secret checks still run.
