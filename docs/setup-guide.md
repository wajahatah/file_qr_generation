# Setup Guide

From nothing to a scannable QR code. Windows-first, since that is where this runs.

**Contents**

1. [Run it](#1-run-it)
2. [Where settings live](#2-where-settings-live)
3. [Issue your first QR](#3-issue-your-first-qr)
4. [Scan it with your phone](#4-scan-it-with-your-phone)
5. [Google Drive storage](#5-google-drive-storage) ← *where your service account and folder ID go*
6. [Going live for customers](#6-going-live-for-customers)
7. [Troubleshooting](#7-troubleshooting)

---

## 1. Run it

Double-click **`start.cmd`**, or from a terminal:

```
start.cmd
```

That is the whole thing. On first run it creates the virtual environment, installs
dependencies, and writes a `.env` with a freshly generated admin token. On every later
run it reuses all of that — it never overwrites your `.env`.

| Command | What it does |
|---|---|
| `start.cmd` | localhost:8000. Only this machine can open the links. |
| `start.cmd lan` | Binds to your Wi-Fi so a **phone can scan**. See §4. |
| `start.cmd 9000` | Different port. |
| `start.cmd lan 9000` | Both. |

Stop it with **Ctrl+C**.

> **An environment already exists in this project.** `.venv\` was created during
> development from Python 3.13.7 at
> `C:\Users\LT\AppData\Local\Programs\Python\Python313\`, with all dependencies
> installed. `start.cmd` detects and reuses it — it will not rebuild or replace it.
>
> Note that plain `python` on this machine resolves to **miniconda**, not that
> interpreter. `start.cmd` always calls `.venv\Scripts\python.exe` explicitly, so this
> does not matter in practice — but it does if you run commands by hand.

## 2. Where settings live

Everything is in **`.env`** in the project root, created for you on first run. It is
gitignored and never overwritten.

| Setting | What it is |
|---|---|
| `BASE_URL` | **The origin baked into every QR.** See the warning below. |
| `ADMIN_TOKEN` | Password for all `/api/` routes. Generated for you; keep it secret. |
| `STORAGE_BACKEND` | `local` (default) or `drive`. |
| `STORAGE_DIR` | Where PDFs go when backend is `local`. |
| `DRIVE_FOLDER_ID` | §5. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | §5. |
| `DRIVE_SCOPE` | §5, only if uploads fail. |
| `DB_PATH` | SQLite file holding tokens and the access log. |
| `DEFAULT_EXPIRY_DAYS` | Default `30`. |
| `MAX_UPLOAD_BYTES` | Default 25 MB. |
| `LOG_RETENTION_DAYS` | Default 90. |

> ### The one setting that is expensive to get wrong
>
> `BASE_URL` is written into each QR **at the moment the code is generated**.
> Changing it later does **not** fix QR codes you have already printed or sent —
> those keep pointing at the old address forever.
>
> Get it right before you issue a single customer-facing QR.
>
> While `BASE_URL` is a local address, `start.cmd` keeps it in sync with the port
> you actually launched on. Once you set a real domain, the launcher leaves it alone.

## 3. Issue your first QR

Easiest way: open **`http://localhost:8000/docs`**, click **Authorize**, paste your
admin token from `.env`, then use `POST /api/files`.

By command line:

```bash
curl -X POST http://localhost:8000/api/files ^
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" ^
  -F "file=@samples/90374749.pdf" ^
  -F "expires_in_days=7" ^
  -F "max_downloads=2" ^
  -F "label=Quotation 4130334 v1"
```

You get back a token, a URL, and the QR as base64 PNG. To save the image directly:

```bash
curl -s "http://localhost:8000/api/files/TOKEN/qr.png" ^
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" -o quotation-qr.png
```

Upload options — all optional:

| Field | Default | Meaning |
|---|---|---|
| `expires_in_days` | 30 | Link dies after this many days. |
| `no_expiry` | false | `true` for a permanent link. |
| `max_downloads` | unlimited | Link dies after this many successful opens. |
| `label` | — | Your own note, e.g. `Quotation 4130334 v1`. Never shown to the customer. |

## 4. Scan it with your phone

`start.cmd` alone produces QR codes pointing at `localhost`, which means **this
machine only** — your phone cannot resolve it. For a real scan test:

```
start.cmd lan
```

It detects your Wi-Fi address and generates QRs pointing there instead:

```
Server URL : http://192.168.2.106:8200
```

Then:

1. Put your phone on the **same Wi-Fi network**.
2. Allow the connection if Windows Firewall prompts.
3. Issue a QR (§3) and scan it with the phone camera.

This is a testing mode, not a deployment. LAN links break when your machine's IP
changes, and they never work from outside your network — for that you need §6.

## 5. Google Drive storage

**This is where your service account key and folder ID go.**

The app is running on `local` storage right now, which works fully. Drive is optional.

> ### Read this before you start
>
> A Google **service account has no Drive storage quota of its own**. If it uploads
> into a normal folder in a personal Gmail account, the file is owned by the service
> account and Google rejects it with `storageQuotaExceeded`.
>
> - **Google Workspace + a Shared Drive → works.** Storage is billed to the shared
>   drive, not the service account. This is the supported path.
> - **Personal Gmail → expect it to fail.** Stay on `local` storage, or use OAuth user
>   credentials instead of a service account (not implemented here).
>
> This is exactly the account-tier question raised in the spec. It is a Google
> platform limitation, not something this code can work around.
>
> **The Drive backend has never been run against live Drive** — it is written but
> unverified, because no credentials were available during development. Treat the
> first real run as a test.

### Step 1 — Create a Google Cloud project

Go to <https://console.cloud.google.com/> → project dropdown → **New Project**.
Name it anything, e.g. `qr-file-share`.

### Step 2 — Enable the Drive API

**APIs & Services** → **Library** → search "Google Drive API" → **Enable**.

### Step 3 — Create a service account

**APIs & Services** → **Credentials** → **Create Credentials** → **Service account**.

Give it a name, e.g. `qr-file-share-sa`. Skip the optional role and user steps.

When created, copy its **email address** — it looks like:

```
qr-file-share-sa@qr-file-share-123456.iam.gserviceaccount.com
```

You need this in step 5.

### Step 4 — Download the JSON key

Click the service account → **Keys** tab → **Add Key** → **Create new key** → **JSON**
→ **Create**. A `.json` file downloads.

**Put that file in the project root and rename it `service-account.json`:**

```
C:\wajahat\personal\learning\waqar_mamo\file_qr\service-account.json
```

That exact filename is already in `.gitignore`. It is a **credential — treat it like a
password.** Never commit it, never email it, never paste it into a chat.

To keep it elsewhere, set the path in `.env`:

```
GOOGLE_SERVICE_ACCOUNT_FILE=C:\secure\path\my-key.json
```

### Step 5 — Create the folder and share it

**Workspace (recommended):** create a **Shared Drive** in Drive, open **Manage
members**, add the service account email from step 3 as **Content manager**.

**Personal Gmail:** create a normal folder, right-click → **Share**, add the service
account email with **Editor** access. (See the quota warning above — this path
commonly fails.)

### Step 6 — Get the folder ID

Open the folder in Drive and look at the address bar:

```
https://drive.google.com/drive/folders/1a2B3cD4eFgHiJkLmNoPqRsTuVwXyZ
                                        └──────── this is the ID ────────┘
```

Copy everything after `/folders/`.

### Step 7 — Put it in `.env`

Open `.env` and set three values:

```
STORAGE_BACKEND=drive
DRIVE_FOLDER_ID=1a2B3cD4eFgHiJkLmNoPqRsTuVwXyZ
GOOGLE_SERVICE_ACCOUNT_FILE=./service-account.json
```

Restart with `start.cmd`. It will warn you at startup if the key file is missing or
the folder ID is empty.

### If uploads fail

| Error | Cause | Fix |
|---|---|---|
| `Service Accounts do not have storage quota` / `storageQuotaExceeded` | The quota limitation above. | Use a Workspace Shared Drive. On personal Gmail, stay on `local`. |
| `404` / `File not found: <folder id>` | Folder not shared with the service account, or the scope is too narrow. | Re-check step 5. If it persists, set `DRIVE_SCOPE=https://www.googleapis.com/auth/drive` in `.env` and restart. |
| `403 insufficientPermissions` | Service account has view access only. | Give it Editor / Content manager. |
| `service account key not found` | Wrong path. | Check `GOOGLE_SERVICE_ACCOUNT_FILE` against where the file actually is. |

### What does *not* change

Drive files are **never link-shared**. The app reads them with its own credentials and
streams the bytes to the customer. Drive is storage only — every expiry, download cap
and revocation rule still runs in this app. That is deliberate: a public Drive link
would be reachable independently of this service and would make all of those controls
meaningless.

## 6. Going live for customers

LAN mode is for testing. For a customer anywhere in the world you need a public
HTTPS address.

1. Deploy to a host with a domain and TLS (Render, Railway, Fly, or a company VM).
2. Set `BASE_URL` in `.env` to that origin, e.g. `https://qr.yourcompany.com`, **before
   issuing any QR**. `start.cmd` will then stop overriding it.
3. Set a strong `ADMIN_TOKEN`.
4. Add a rate limit on `/d/` at your reverse proxy — the app does not rate-limit itself.
5. Behind a proxy, run uvicorn with `--proxy-headers` so the access log records the real
   caller and not the proxy.
6. **Back up `DB_PATH`.** The tokens live only there. Lose that file and every QR in
   circulation stops working, permanently.

Free hosting tiers cold-start — the first scan of the day can take 10–30 seconds of
blank screen. Worth paying to avoid if a customer is standing in front of you.

## 7. Troubleshooting

**"Python was not found on PATH"** — install Python 3.11+ from python.org and tick
*Add python.exe to PATH*.

**QR scans but the phone shows nothing / cannot connect** — the QR encodes
`localhost`. Use `start.cmd lan` (§4). Check the printed Server URL is a `192.168.x.x`
style address.

**Phone on the same Wi-Fi still cannot connect** — Windows Firewall blocked it. Allow
Python through on private networks, and confirm the Wi-Fi is marked *Private*, not
*Public*.

**Port already in use** — run on another port: `start.cmd 8080`.

**Customer says the link is dead** — check the true reason:

```bash
curl "http://localhost:8000/api/files/TOKEN/log" -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

The customer always sees the same neutral page regardless of cause; the log tells you
whether it expired, was revoked, or hit its download cap. That asymmetry is
intentional — see §5 of the [feature docs](qr-file-share.md).

**Lost the admin token** — it is in `.env`. To rotate it, edit that file and restart.
Existing QR codes are unaffected; they do not depend on the admin token.

**Everything looks broken** — delete `file_qr.db` and `storage/` to reset. This
destroys every issued link permanently. Do not do it in production.
