# Setup Guide

From nothing to a QR code a customer can scan. Written for Windows.

Want the short version? See [HOW-TO-RUN.md](../HOW-TO-RUN.md).

**Contents**

1. [What this app does](#1-what-this-app-does)
2. [Start the app](#2-start-the-app)
3. [Connect Google Drive — one-time setup](#3-connect-google-drive--one-time-setup)
4. [Make a QR code](#4-make-a-qr-code)
5. [Time limits](#5-time-limits)
6. [Managing issued QR codes](#6-managing-issued-qr-codes)
7. [Install it as a desktop app](#7-install-it-as-a-desktop-app)
8. [Troubleshooting](#8-troubleshooting)
9. [Running in Docker instead](#9-running-in-docker-instead)
10. [Moving the app to another laptop](#10-moving-the-app-to-another-laptop)

---

## 1. What this app does

You drop a PDF into the app. It uploads the PDF to **your own Google Drive** and gives
you a QR code. Anyone who scans the QR code with their phone camera opens the PDF —
**even when this laptop is switched off**, because the file is served by Google Drive,
not by the laptop.

Every QR code has a **time limit** you choose. When it runs out, the app removes the
file from sharing and the QR code stops working.

Two things to know up front:

- **The customer's phone needs internet.** A QR code holds at most about 3 KB; a PDF
  is far bigger. The QR code holds a *link* to the file, never the file itself.
- **The app removes expired files when it runs.** If the laptop is off when a time
  limit runs out, the QR code keeps working until the next time you start the app.
  See [§5](#5-time-limits).

## 2. Start the app

Double-click **`start.cmd`** in the app folder.

The first run takes a minute: it prepares Python, installs what the app needs, and
creates a `.env` settings file with your **admin token** — a long password shown in
the black window. Later runs start in a few seconds.

Your browser then opens the app by itself. Sign in with the admin token. You stay
signed in for 12 hours.

**Keep the black window open while you use the app.** Closing it, or pressing Ctrl+C
in it, stops the app.

| | |
|---|---|
| App address | `http://localhost:8000/admin` |
| Different port | `start.cmd 9000` |
| Admin token | Shown in the black window; also in the `.env` file |

The app only accepts connections from this laptop. Nothing on your network — not
even the same Wi-Fi — can reach it.

> **About the `.venv` folder.** It holds the app's private copy of Python and its
> libraries. `start.cmd` creates it once and reuses it.
>
> It only works on the computer that created it. **When copying the app to another
> laptop, leave `.venv` out** (or delete it after copying) — `start.cmd` builds a
> fresh one there.

## 3. Connect Google Drive — one-time setup

The app needs permission to upload to your Google Drive. Google requires you to
register the app once in Google Cloud. It takes about 10 minutes and is free.

Works with an ordinary Gmail account and with Google Workspace.

### Step 1 — Create a Google Cloud project

1. Go to <https://console.cloud.google.com/> and sign in with the Google account whose
   Drive should hold the files.
2. Click the project picker at the top → **New Project**. Name it `QR File Share` →
   **Create**. Make sure it is selected afterwards.

### Step 2 — Turn on the Google Drive API

**APIs & Services** → **Library** → search **Google Drive API** → **Enable**.

### Step 3 — Set up the sign-in screen

Open **Google Auth Platform** (older consoles call it **OAuth consent screen**) and
click **Get started**.

1. **App name:** `QR File Share`. **Support email:** your email.
2. **Audience:** choose **External** for a Gmail account. (On Google Workspace choose
   **Internal** instead — then skip item 5; see the box below.)
3. **Contact email:** your email. Agree to the policy → **Create**.
4. **Data Access** → **Add or remove scopes** → find and tick
   `.../auth/drive.file` ("See, edit, create and delete only the specific Google
   Drive files you use with this app") → **Update** → **Save**.
5. **Audience** → **Test users** → **Add users** → enter the Gmail address whose Drive
   will hold the files → **Save**. Leave the publishing status as **Testing**.

On the **Branding** page, **do not upload a logo** (it triggers a Google review) and
leave the home page, privacy policy and authorised domain empty.

> ### Why the app stays in "Testing"
>
> Publishing an External app ("In production") requires a **home page**, a **privacy
> policy page** and an **authorised domain** — a website on a domain you own. Google
> does not accept free hosts such as GitHub Pages as your own domain. For one person
> using their own app, that is not worth it.
>
> **The cost of Testing:** Google signs the app out after **7 days**. The app then shows
> **Reconnect Google Drive**; click it and sign in. Until you do, expired QR codes
> cannot be removed, and the app shows a warning saying how many are waiting.
>
> On **Google Workspace**, choose **Internal** in item 2 instead: Internal apps are not
> signed out weekly and need no test users.

### Step 4 — Create the app's key

1. **Google Auth Platform** → **Clients** → **Create client**.
2. **Application type:** **Desktop app**. Name: `QR File Share` → **Create**.
3. Click **Download JSON**.
4. Rename the downloaded file to **`client_secret.json`** and put it in the app folder,
   next to `start.cmd`.

It must be a **Desktop app** client. A "Web application" client will not work, and the
app tells you so if you use one.

`client_secret.json` is excluded from git. Do not email it or share it.

### Step 5 — Connect

Restart the app (close the black window, double-click `start.cmd`). Click **Connect
Google Drive**. Google's sign-in opens in your browser:

1. Choose your account.
2. If Google shows **"Google hasn't verified this app"**: this is your own app. Click
   **Advanced** → **Go to QR File Share**.
3. Allow access.
4. Close that tab and return to the app. The top bar now shows
   **Google Drive: your@email**.

The app remembers the connection, stored in **Windows Credential Manager** — not in a
file in the app folder.

### What the app can see in your Drive

**Only the files it uploaded.** It cannot see, open or change anything else in your
Drive. Its files go into a folder it creates called **QR File Share**.

## 4. Make a QR code

1. **Drop a PDF** onto the box, or click it to choose a file. Up to 25 MB.
2. **Label** (optional) — for example `Quotation 4130334`. Only you see it.
3. **Choose how long it should work** — see [§5](#5-time-limits).
4. Click **Create QR code**.

The QR code appears with four buttons:

| Button | What it does |
|---|---|
| **Download PNG** | Saves the QR code as an image. |
| **Copy image** | Copies the QR code — paste straight into WhatsApp Web, Outlook or Word. |
| **Copy link** | Copies the Google Drive link, for sending as text. |
| **Print** | A printable page: the QR code, your label, and *"Scan with your phone camera to download."* |

When a customer scans it, their phone opens the PDF in Google Drive, with a download
button. They do not need a Google account or any app.

## 5. Time limits

```
 How long should this QR code work?

 [ 1 day ]  [ 3 days ]  [ 7 days ]  [ 30 days ]     or pick a date [ dd/mm/yyyy ]

 ✓ Customers can open this until Mon 5 Oct 2026, 11:59 PM (7 days)
```

- Click a button, or pick any date from today up to one year ahead.
- The green sentence tells you the exact last day, in words, before you create anything.
- **A limit covers the whole of its last day**, until 11:59 PM by this laptop's clock.
  "Until 5 October" means customers can open it all day on 5 October.
- Every QR code has a limit. There is no "forever".

**Your default** — the button selected when you start — is set in **Settings →
New QR codes last**. Changing it affects new QR codes only.

### When the laptop is off

Google Drive cannot expire a shared link by itself, so the app does it: when it
starts, and every 10 minutes while it runs, it removes every file whose time is up.

If the laptop is off when a limit runs out, that QR code keeps working until you next
start the app. Starting the app removes it straight away.

For a limit to take effect on time, have the app running when it runs out — or accept
that it may run over until you next start the app.

## 6. Managing issued QR codes

Everything you have issued is listed under **Issued QR codes**, newest first, with
its status in plain words:

| Status | Meaning |
|---|---|
| **Active** · until Mon 5 Oct (7 days left) | Working. |
| **Expires today** at 11:59 PM | Last day. |
| **Expired — removing now** | Past its limit but not yet removed — the laptop was off, or Google Drive was unreachable. It still works until it is removed. |
| **Expired** · 3 Oct — can be reactivated for 27 days more | Removed. Can be brought back. |
| **Ended** · 1 Oct | Ended on purpose. Final. |

On each one:

| Action | Effect |
|---|---|
| **Show QR** | Shows the QR code again, with the download / copy / print buttons. |
| **Copy link** | Copies the Google Drive link. |
| **Change limit** | Add 7 or 30 days, or pick a new date — earlier or later. **The same QR code keeps working; nothing needs reprinting or resending.** |
| **End now** | Stops it immediately. Cannot be undone — issue a new QR code instead. |
| **Reactivate** | For an **expired** QR code, within 30 days: choose a new limit and **the same QR code works again**. After 30 days Google empties its trash and this is no longer possible. |

**Something went wrong with a QR code a customer has?** End it, and issue a new one.

### Disconnecting Google Drive

**Settings → Disconnect Google Drive.** QR codes already issued keep working, but
expired ones cannot be removed until you connect again — the app shows a warning if
any are waiting.

## 7. Install it as a desktop app

In **Microsoft Edge** or **Google Chrome**, with the app open, click the install icon
at the right end of the address bar (or **⋯ → Apps → Install this site as an app**).
It then gets its own window, a Start-menu entry and a taskbar icon.

`start.cmd` must still be running for the installed app to work.

> Not yet verified: this was tested only in an embedded browser that does not support
> installing apps. Check it on the laptop in Edge or Chrome.

## 8. Troubleshooting

**"Python was not found on PATH"** — install Python 3.11 or newer from
<https://www.python.org/downloads/>, ticking **Add python.exe to PATH**.

**The app says "Google Drive is not set up yet"** — `client_secret.json` is not in
the app folder, or has a different name. See [§3 step 4](#step-4--create-the-apps-key).

**"… is a 'web' OAuth client. It must be a 'Desktop app' client"** — you created the
wrong kind of client in step 4. Create a **Desktop app** one and download it again.

**"Sign-in was not completed within 5 minutes"** — click Connect again and finish
signing in within 5 minutes.

**"Google sign-in has expired or was revoked"** — click **Connect Google Drive**
again. About once a week this is expected: the app is in **Testing** (see
[§3 step 3](#step-3--set-up-the-sign-in-screen)).

**"Access blocked" or "has not completed the Google verification process"** — the
Gmail you signed in with is not a test user. Add it in [§3 step 3, item 5](#step-3--set-up-the-sign-in-screen).

**"Could not reach Google Drive"** — check the laptop's internet connection. Nothing
is lost; try again.

**The browser did not open by itself** — go to `http://localhost:8000/admin`.

**Port already in use** — start on another port: `start.cmd 8080`.

**Lost the admin token** — it is in the `.env` file in the app folder. To change it,
edit that file and restart.

**A customer says the QR code does not work** — find it in **Issued QR codes** and read
its status. If it expired or was ended, change or reactivate it, or issue a new one.

## 9. Running in Docker instead

An alternative to `start.cmd`. The app runs in the background with no window to keep
open, starts by itself with Docker Desktop, and needs **no Python** on the laptop.

### What you need

- **Docker Desktop**, installed and running. Free for personal use, education and
  small businesses; a company with more than 250 employees or more than $10M yearly
  revenue needs a paid Docker licence.
- `client_secret.json` next to `docker-start.cmd`, as in [§3](#3-connect-google-drive--one-time-setup).

### Start

Double-click **`docker-start.cmd`**. It:

1. checks Docker Desktop is running;
2. checks `client_secret.json` is there;
3. creates `.env` with an admin token if there is none (an existing `.env` is kept);
4. reads the laptop's time zone;
5. builds and starts the app, waits until it answers, and opens your browser.

The first run downloads and builds for a few minutes; later runs take seconds.

Then sign in with the admin token, click **Connect Google Drive**, and — because the
app cannot open a browser from inside Docker — click **Continue to Google**. The
Docker app keeps its own Google sign-in, separate from `start.cmd`'s.

### Or with plain `docker compose` (git workflow)

`compose.yaml` in the project root builds from source. On any laptop with Docker:

```
git pull
copy .env.example .env
```

In `.env`, set `ADMIN_TOKEN` to a long random value and **uncomment `TZ`** with that
laptop's zone (e.g. `TZ=Asia/Riyadh`). Put `client_secret.json` in the project root.
Then:

```
docker compose up -d --build
```

Open `http://localhost:8000/admin`. `.env` and `client_secret.json` are gitignored, so
each laptop needs its own copy. **Set `TZ`**: without `docker-start.cmd` nothing
passes the laptop's zone in, so the app would count limits in UTC (and warn you).

### Always on

The app restarts by itself whenever Docker Desktop starts. Turn on **Docker Desktop →
Settings → General → Start Docker Desktop when you sign in to your computer**, and the
app is ready whenever the laptop is on — which also means expired QR codes are removed
on time whenever the laptop is on.

`docker-stop.cmd` stops it. Nothing is deleted.

### Time zone and travel

Time limits end at midnight in the app's time zone. `docker-start.cmd` passes the
laptop's current zone every time it runs, so after travelling:

1. set the laptop to the new zone (**Windows Settings → Time & language → Date & time**);
2. double-click `docker-start.cmd` once.

No rebuild is needed. If the app and the laptop disagree — for example Docker
restarted the app at login with the old zone — the app shows a warning saying so.

To force one zone regardless of the laptop, add a line to `.env`, e.g.
`TZ=Asia/Riyadh`, and run `docker-start.cmd`. The zone in use is shown in **Settings**.

### Where the data lives

In a Docker volume named `qr-file-share_qr-data`: the database of issued QR codes,
settings, and the Google sign-in token (in a file only the app's user can read). It
survives restarts, `docker-stop.cmd`, and rebuilding the app. Only
`docker compose down -v` deletes it.

### Things to know

- **Use `start.cmd` or Docker, not both.** They keep separate lists of QR codes and
  separate Google sign-ins, and both use port 8000.
- **Updating the app:** after replacing the app's files with a newer version, run
  `docker-start.cmd` — it rebuilds automatically. Your data is kept.
- **Another port:** `docker-start.cmd 9000`. The Google sign-in return port, 8766, is
  fixed and must be free.
- The app is reachable only from this laptop (`127.0.0.1`), the same as `start.cmd`.

### Docker troubleshooting

**"Docker Desktop is not running"** — start it, wait for *Engine running*, run
`docker-start.cmd` again.

**"port is already allocated"** — something else is using port 8000, usually the
`start.cmd` window. Close it, or use `docker-start.cmd 9000`.

**The app warns the time zone is wrong** — run `docker-start.cmd` once.

**After approving on Google, the page says "This site can't be reached"** — port 8766
is blocked or in use. Close other programs using it and try **Connect Google Drive**
again.

**Something else** — see what the app reported: in the app folder, run
`docker compose logs --tail 50 app`.

## 10. Moving the app to another laptop

The **kit** is one zip with the app ready-built for Docker. On the other laptop nothing
is built, no source code is needed, and no Python is installed.

### Make the kit (this laptop)

Double-click **`make-kit.cmd`**. It runs all the tests first (no kit is made from
failing code), builds the app for both Intel/AMD and ARM laptops, checks that no
password or key file got in, and writes:

```
dist\qr-file-share-kit-<date>-<commit>.zip
```

The ARM build is emulated and takes 15 minutes or more. For an Intel/AMD-only kit
in a minute or two, run from the app folder:
`.venv\Scripts\python.exe tools\make_kit.py --arch amd64`. Commit your changes first: a kit
made from uncommitted changes gets `-dirty` in its name so you can tell.

### Put it on GitHub

GitHub refuses files over 100 MB inside a repository, and the kit is bigger, so it
goes in a **Release** (files up to 2 GB):

1. On github.com, open the repository → **Releases** → **Draft a new release**.
2. **Choose a tag** → type the kit's version, e.g. `v2026.10.04-6af9929` → **Create new tag**.
3. Drag the zip into **"Attach binaries"**.
4. **Publish release**.

The repository is private, so downloading needs you signed in to GitHub on the other
laptop.

### On the other laptop

1. Install WSL and Docker Desktop — the commands are in `START-HERE.md` inside the kit.
2. Download the zip from the Release and unzip it, e.g. to `C:\QR File Share`.
3. Put `client_secret.json` in that folder — the same key file works on any laptop.
4. Double-click **`docker-start.cmd`**. It picks the right version for the laptop's
   processor, loads it into Docker, starts it and opens the browser.
5. Sign in with the admin token, **Connect Google Drive**, done.

### Updating

Make a new kit, unzip it **over** the old folder (keep `.env` and `client_secret.json`),
double-click `docker-start.cmd`. The new version is loaded; QR codes, settings and the
Google sign-in are kept.

### Each laptop is its own app

Each keeps its own list of QR codes and its own Google sign-in, and removes only its
own expired QR codes. A QR code made on one laptop is managed on that laptop.
