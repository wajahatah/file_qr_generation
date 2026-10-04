# Spec — Laptop App, Google Drive Delivery Only (Phase 1b)

- **Status:** APPROVED 2026-09-28 — IMPLEMENTED. See [../qr-file-share.md](../qr-file-share.md).
- **Author:** Claude (Opus 5.5), on behalf of Wajahat Ahmed
- **Date:** 2026-09-28 (v3 supersedes v1 and v2 of the same day)
- **Builds on:** [spec-qr-file-share.md](spec-qr-file-share.md) (approved, implemented)
- **Scope:** a laptop app that uploads a PDF to Google Drive, issues a QR code for it,
  and removes it when the user's time limit runs out.

**What changed from v2:** the "download from this laptop" mode is dropped. Google
Drive is the only delivery path. The code that served files from the laptop is
removed (§8).

---

## 1. Decisions

| Question | Answer | Date |
|---|---|---|
| Hosting | None. Runs on the laptop only. | 2026-09-28 |
| Delivery | **Google Drive only.** No download from the laptop. | 2026-09-28 |
| Uploader's device offline | Customers must still get the file. | 2026-09-28 |
| Limit | Set by the user, and **easy to set**. | 2026-09-28 |
| App form | Laptop app. | 2026-09-28 |
| Users | One person. | 2026-09-28 |
| Admin session | 12 hours. | 2026-09-28 |

**Assumption — please confirm:** "limit" means a **time limit**, i.e. the date after
which the QR stops working. A download-count limit is not possible: Google Drive does
not report downloads to the app, so there is nothing to count.

---

## 2. Facts this design is built on

**2.1 Google Drive cannot expire a public link by itself.** Drive supports expiry
dates only on shares with named people or groups — never on "anyone with the link"
shares, which is what a QR needs. Verified against the Drive API reference
(`permissions.expirationTime`: *"They can only be set on user and group
permissions"*). **So the app enforces the limit itself** (§5).

**2.2 A scanning phone with no internet cannot get the PDF.** The largest QR code
holds 2,953 bytes of binary data; the smallest sample PDF is 68,031 bytes. Measured.
Permanently out of scope.

---

## 3. How it works

```
LAPTOP (app, this computer only)            GOOGLE DRIVE (always online)
  1. drop in PDF, pick a limit  ──upload──▶  file in "QR File Share" folder,
  2. QR shown: save / copy / print           shared as "anyone with the link"
  3. every 10 min: remove expired ──trash──▶  expired file → trash → link dead
                                                        ▲
CUSTOMER'S PHONE                                        │
  camera scans QR ── opens the Drive link ──────────────┘
  (no app, no Google account needed; laptop can be off)
```

The QR encodes the Drive link directly. The customer sees Google Drive's PDF viewer
with a download button.

---

## 4. Setting the limit — the core of the app

The limit is the only control, so it gets the most care.

### 4.1 When issuing a QR

One row of buttons, one click:

```
 How long should this QR work?

 [ 1 day ]  [ 3 days ]  [ 7 days ]  [ 30 days ]  [ Pick a date… ]

 ✓ Customers can open this until  Sun 5 Oct 2026, 11:59 PM  (7 days)
```

- **Presets** — 1, 3, 7, 30 days. The user's default (§4.3) is pre-selected.
- **Pick a date** opens a calendar. Any date from today up to one year ahead.
- **The sentence under the buttons updates instantly**, in plain words with the real
  date. The user never has to work out what "7 days" means.
- **The limit ends at 11:59 PM on the chosen day**, laptop time. "Until 5 October"
  then means all of 5 October — what a person expects. Stored as UTC internally.
- **No "never expires" option.** Every QR has a limit, per the requirement. A
  forgotten permanent public link is the main way a quotation leaks. Easy to add later
  if wanted.

### 4.2 Changing the limit after the QR is sent

The QR points at the Drive file, and the limit lives in the app — so **the limit can
be changed at any time without reprinting or resending the QR.**

On each issued link:

| Action | Effect |
|---|---|
| **Extend** | +7 days, +30 days, or pick a new date. |
| **Shorten** | Pick an earlier date. |
| **End now** | The link dies immediately. (Same as revoke.) |
| **Reactivate** | For an **expired** link, within 30 days: restores the file from Drive trash with a new date. **The same QR works again** — the customer does not need a new one. |

Revoked links cannot be reactivated. Revoke is a deliberate kill; the user issues a
new QR instead.

### 4.3 Default limit

Settings screen: **"New QR codes last: [ 7 days ▾ ]"**. Remembered by the app,
changeable any time, applies to new QR codes only.

### 4.4 Seeing where each link stands

The issued-links list shows the limit in plain words, not timestamps:

| Status | Shown as |
|---|---|
| More than a day left | **Active** · until Sun 5 Oct (6 days left) |
| Last day | **Expires today** at 11:59 PM |
| Past the limit, removed | **Expired** · 3 Oct — *Reactivate* available for 27 more days |
| Past the limit, not yet removed (§5) | **Expired — removing now** |
| Revoked | **Ended** · 1 Oct |

---

## 5. How the limit is enforced — and its one weakness

Because Drive cannot do it (§2.1), the app does:

- **On startup, and every 10 minutes while running**, the app moves every file past
  its limit to the Drive trash. The link dies; the customer sees Google's
  "file not found" page.

**The weakness:** the app can only do this while it is running. If the laptop is off
or asleep when a limit is reached, the link keeps working until the app next starts.
A 1-day limit on a Friday, with the laptop off all weekend, would work until Monday.

The app states this at the moment of issuing, in one line under the limit sentence:

> The link is removed by this app. If the laptop is off when the time is up, it is
> removed the next time the app starts.

**Closing the gap is possible but not proposed now** — see open question 1.

---

## 6. Screens

**Login** — admin token, typed once, 12-hour session.

**Connect Google Drive** — shown until connected. One button → Google sign-in → done.

**Issue a QR** (main screen)
1. Drop in a PDF (or browse). Checked before upload; re-checked on the server.
2. Optional label, e.g. *Quotation 4130334*. Only the user sees it.
3. The limit (§4.1).
4. **Create QR** → the QR shown large, with **Download PNG**, **Copy image** (paste into
   WhatsApp Web, Outlook, Word), **Copy link**, **Print** (QR + label + *"Scan with
   your phone camera to download."*).

**Issued links** — newest first: label, filename, status (§4.4), created. Per row:
show QR, copy link, change limit (§4.2), end now.

**Settings** — default limit (§4.3); connected Google account; **Disconnect**.

Installable from Edge or Chrome as a desktop app (own window, taskbar icon).

---

## 7. Google Drive connection

**Sign-in:** Google's standard flow for desktop apps. The app opens the browser, the
user signs into **their own** Google account, Google hands the app a token. The
user's password never touches the app. Works on personal Gmail and Workspace alike.

**Permission:** `drive.file` only — the app can see and change **only files it
uploaded itself**, nothing else in the user's Drive. Non-sensitive, so Google
requires no verification process.

**Consequence of `drive.file`:** the app cannot write into a folder the user made by
hand. It creates and uses its own folder, **QR File Share**. The earlier
`DRIVE_FOLDER_ID` setting is removed.

**Token storage:** Windows Credential Manager via `keyring` — encrypted by Windows,
not a file in the project folder.

**One-time setup** (full walkthrough in the setup guide):
1. Google Cloud project; enable the Drive API.
2. OAuth consent screen; **publish it to "In production"**. Left in "Testing", Google
   expires the sign-in after **7 days** and the user is logged out weekly. (Workspace
   accounts can pick *Internal* instead, which is exempt.)
3. Create an OAuth client of type **Desktop app**; save its JSON as
   `client_secret.json` in the project folder (gitignored).

Google may show "Google hasn't verified this app" at sign-in. It is the user's own
app; *Advanced → continue*. The guide says so.

### 7.1 Never leave a public file the app does not know about

The dangerous failure is a file shared publicly on Drive with no record in the app —
nothing would ever expire it, making it a **permanent public link**. So issuing is
ordered, with cleanup on every failure:

1. Upload the file (private).
2. Record it in the app database.
3. Only then share it as "anyone with the link".
4. If step 2 or 3 fails, the uploaded file is moved to trash and the user sees the
   error. No QR is shown.

The removal sweep also treats "file already gone from Drive" (deleted by hand) as
removed, rather than failing forever.

---

## 8. What gets removed

Drive-only makes the laptop-delivery system from the first spec unused. Dead code is
still code to maintain, and a network listener with no purpose is attack surface. So
it is removed rather than left dormant.

### 8.1 Preserve first

There is **no git history** — anything deleted is gone for good. Before removing
anything:

- `git init`, commit the current working system as-is, tag it
  **`phase-1-laptop-delivery`**.

It stays fully recoverable if laptop delivery is ever wanted again. **Needs your
approval** — it creates a git repository in the project folder.

### 8.2 Removed

| Removed | Why |
|---|---|
| `/d/{token}` download route + `unavailable.html` | QR codes now point at Drive. |
| Download caps, `try_consume_download` | Drive does not report downloads. |
| `access_log`, the log endpoint, log purge, IP truncation | Nothing downloads through the app. |
| `app/storage.py` (local disk + service-account Drive) | Replaced by `app/drive.py` (§7). The service-account version never ran and cannot work on personal Gmail. |
| `BASE_URL`, `start.cmd lan`, port-following logic | Nothing is served to phones any more. |
| `samples/` use in download tests | Replaced by Drive-flow tests. |
| The 128-bit public token | Nothing public needs one; links get a plain internal ID. |

### 8.3 Kept

- FastAPI — it serves the app screens and talks to Drive.
- `app/qr.py` and its round-trip tests — now encoding the Drive link.
- Upload validation (PDF magic bytes, size cap) and its tests.
- Bearer-token API access for scripting (`curl` keeps working).
- `start.cmd` — simplified; opens the app in the browser by itself.

### 8.4 Security gain

The server binds to **`127.0.0.1` only**. Nothing on the laptop accepts connections
from the network any more — not even from the same Wi-Fi.

---

## 9. Data model

Fresh schema. There is no existing data (verified: the app has not been run since
test cleanup). If an old-format database is ever found, it is renamed to
`file_qr.db.phase1.bak`, never deleted.

```sql
CREATE TABLE links (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    drive_file_id TEXT NOT NULL UNIQUE,
    drive_url     TEXT NOT NULL,          -- what the QR encodes
    filename      TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    label         TEXT,
    created_at    TEXT NOT NULL,          -- UTC ISO-8601
    expires_at    TEXT NOT NULL,          -- UTC; always set (§4.1)
    revoked_at    TEXT,                   -- "End now" / revoke
    removed_at    TEXT                    -- when trashed on Drive; NULL while live
);

CREATE TABLE admin_sessions (id_hash TEXT PRIMARY KEY, created_at TEXT, expires_at TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- default limit
```

`expires_at IS NOT NULL` makes §4.1's "every QR has a limit" a database rule, not
only a UI rule.

---

## 10. Admin authentication

A server on `127.0.0.1` is still reachable by **any web page open in the same
browser**, which can make the browser send requests to `localhost`. So the login
stays, and so do the protections:

- `require_admin` accepts a **Bearer token** (scripts) **or** a **session cookie** (the
  app).
- Session: 256-bit random; stored as SHA-256 only; `HttpOnly`; `SameSite=Strict`;
  12 hours; logout deletes it.
- **CSRF:** every cookie-authenticated `POST` must carry an `Origin` of this app, or
  gets 403.
- **DNS rebinding:** a malicious site can point its own domain at `127.0.0.1` to get
  around the browser's same-origin rules. Blocked by accepting only requests whose
  `Host` is `localhost` or `127.0.0.1`.
- `Content-Security-Policy: default-src 'self'` and `X-Frame-Options: DENY` on the app.

v2's placeholder-token guard is dropped: it existed for a server reachable from the
internet, which this no longer is.

---

## 11. Security review

| Risk | Mitigation |
|---|---|
| QR forwarded to the wrong person | Accepted. The time limit is the control; "End now" for emergencies. Stated in the app. |
| Limit overrun while laptop is off | Stated at issue time (§5). Open question 1 closes it fully. |
| Public file with no expiry (orphan) | Issue order + cleanup (§7.1); `expires_at NOT NULL`. |
| Google token theft | Windows Credential Manager; `drive.file` limits damage to this app's own files. |
| Attack via another website in the browser | Session cookie flags, Origin check, Host check (§10). |
| Network attacker | Nothing listens beyond `127.0.0.1` (§8.4). |
| `client_secret.json` committed | Gitignored. |
| Script injection | Untrusted text via `textContent` only; CSP. |

---

## 12. Changes by file

| File | Change |
|---|---|
| `app/drive.py` | **New.** Sign-in, `keyring`, folder, upload, share, trash, restore, sweep. |
| `app/admin.py` | **New.** Screens, login/logout, Drive connect/disconnect, settings. |
| `app/limits.py` | **New.** Preset and date → end-of-day UTC; plain-words status (§4.4). Pure functions, unit-tested. |
| `app/main.py` | Rewritten around Drive; `/d/` removed; bearer-or-session auth; sweep scheduler; Host check. |
| `app/db.py` | New schema (§9); old-DB backup; sessions; settings. |
| `app/config.py` | Add `admin_session_hours`, `google_client_secret_file`; remove `BASE_URL`, storage and service-account settings. |
| `app/storage.py`, `app/templates/unavailable.html` | **Deleted.** |
| `app/templates/`, `app/static/` | **New.** App screens, JS, CSS, manifest, icons. |
| `start.cmd`, `tools/setup_helper.py` | Simplified: bind `127.0.0.1`, open the app automatically; `lan` mode and URL logic removed. |
| `requirements.txt` | Add `google-auth-oauthlib`, `keyring`. |
| `tests/` | See §13. |
| `docs/` | Setup guide rewritten; feature docs rewritten; README; first spec annotated as superseded in part; this spec marked implemented. |

---

## 13. Test plan

This rewrites most of the system, so per Rule 6 it is **major**: full suite plus a
literal full-system run.

**Removing tests.** Tests for removed features (download route, caps, access log,
concurrency race, launcher URL logic) are deleted **with** those features — they are
preserved in the `phase-1-laptop-delivery` commit. Tests for everything kept (QR
round-trip, upload validation, bearer auth) are carried over, and must pass
unmodified apart from import paths.

**New, all offline** — Drive is replaced by a fake Drive client defined in the test
suite, never in app code:

- **Limits** (`app/limits.py`): every preset → correct end-of-day; "pick a date" range
  (today to +1 year; past dates rejected); plain-words status for each case in §4.4;
  the date boundary exactly at 11:59:59 PM vs midnight; UTC conversion at +03:00.
- **Issuing:** PDF → uploaded → recorded → shared → QR decodes to the Drive link.
- **Orphan safety (§7.1):** share fails → file trashed, no row, no QR; DB insert fails
  → file trashed, never shared.
- **Sweep:** trashes exactly the expired links, never a live one; tolerates a file
  already deleted by hand; runs on startup.
- **Changing the limit:** extend, shorten, end now; reactivate restores from trash
  with the same Drive link; reactivate refused after 30 days and for revoked links.
- **Default limit:** saved, applied to new QR codes, not retroactive.
- **Auth:** cookie flags; hash-only storage; 12-hour expiry; logout; foreign Origin →
  403; bearer without Origin → OK; wrong Host → rejected.
- **No network listener:** the launcher binds `127.0.0.1` only.

**Full-system run in a real browser**, using a small test launcher (under `tests/`)
that starts the app with the fake Drive client: log in → issue a QR for each sample
PDF with each preset and a picked date → decode each QR from the screen → extend,
shorten, end now, reactivate → change the default → print preview → install as a
desktop app → log out.

**Needs your Google account, so done together at the end:**
1. Real sign-in; real upload of the invoice.
2. **Switch the laptop off, scan the QR on a phone on mobile data** — the test that
   proves the core requirement.
3. A 1-day limit: confirm the link dies after the sweep.
4. Reactivate it: confirm the **same QR** works again.

Until then the Drive code is proven only against the fake client, and will be
reported as that — not as verified.

---

## 14. Out of scope

Hosting · download from the laptop · download-count limits (§1) · scan history ·
multiple users · phone apps · offline scanning (§2.2) · quotation generation (Phase 2).

---

## 15. Open questions

1. **Make the limit exact even when the laptop is off?** Possible with a small
   Google Apps Script running inside the user's own Google account on a timer: free,
   no server, removes expired files hourly whether the laptop is on or not.
   **Costs:** a second one-time setup step, and the script needs access to the user's
   **whole** Drive — Apps Script cannot be narrowed the way the app is. It also cannot
   be tested without the user's account.
   **Recommendation: not now.** Ship with laptop-side removal and the honest warning;
   add the script only if a late removal actually causes a problem.
2. **Confirm "limit" means a time limit** (§1).
3. **Approve the git commit before removal** (§8.1).

---

## 16. Approval

- [x] Approved by Wajahat — 2026-09-28. "Limit" confirmed to mean a time limit.

### Implementation notes (post-build)

Built as specced. Deviations and additions, all recorded here rather than silently:

1. **Git preservation (§8.1)** was done by the user creating the repository; the
   phase-1 system was committed and tagged `phase-1-laptop-delivery` before any
   removal. During that, the full phase-1 README was found overwritten by the GitHub
   initial commit's one-line README; it was restored before the commit so the tag
   reflects phase 1 faithfully.
2. **HTTP 413 / 415 kept** for oversized and non-PDF uploads, as in phase 1, rather
   than a generic 400 — the carried-over upload contract is unchanged.
3. **`Referrer-Policy: same-origin`**, not `no-referrer`. Found in the full-system
   browser run: under `no-referrer` browsers send `Origin: null` on POSTs, which the
   CSRF check (§10) refuses, breaking sign-in and every save. Unit tests could not see
   it because they set `Origin` by hand. Regression tests added; `null` is still
   refused.
4. **Static files served `Cache-Control: no-cache`.** Found in the browser run: a stale
   cached stylesheet survived a server change, so an update could leave a new page
   running old script. Regression test added.
5. **Disabled primary button** given explicit colours (5.84:1 contrast in dark mode).
   Found in the browser run: opacity-dimmed, its label was unreadable.
6. **Preview endpoints** (`/api/limits/preview`, `/api/links/{id}/limit/preview`) added
   so every date sentence comes from one tested server-side implementation, and the
   preview shown is exactly what is saved.
7. **`tests/run_fake_server.py`** added to run the real app against the fake Drive for
   UI testing without a Google account. Test-only; nothing in `app/` refers to it.
8. **`tzdata`** added as a dev dependency so the daylight-saving tests run on Windows.
9. **Consent screen stays in "Testing" (reverses §7 step 2).** Found during the user's
   own setup: Google now refuses to publish an External app to "In production" without
   a home page, privacy policy and an authorised domain owned by the user, and does
   not accept GitHub Pages as one. Guides changed to: add the user as a test user,
   stay in Testing, reconnect weekly. The app already handled an expired sign-in
   (reconnect prompt; sweep-pending warning), so no code change was needed.

**Verified:** 223 automated tests; full-system browser run of sign-in, issuing with
presets and a picked date, on-screen QR → Drive link → exact bytes, change limit
(extend, shorten, past date refused), end now (cancel and confirm), reactivate, default
setting, show QR, print (live and ended), disconnect / reconnect, log out; real
`start.cmd` first run; app not reachable from the LAN address.

**Not yet verified — requires the user's Google account (§13):** live sign-in, live
upload / share / trash / restore, and a phone scan with the laptop off. **Not verified
at all:** "Install app" — the test browser cannot install apps.
