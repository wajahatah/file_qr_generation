# QR File Share — Start Here

This folder is the whole app, ready to run. Five steps. Steps 1 and 2 are done once.

---

## 1. Install WSL and Docker Desktop (once per laptop)

Open **PowerShell as Administrator**: right-click Start → **Terminal (Admin)**.

```powershell
wsl --install --no-distribution
```

**Restart the laptop.** Then, again in PowerShell as Administrator:

```powershell
wsl --update
```

```powershell
winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
```

Start **Docker Desktop** from the Start menu, accept its agreement, and wait until it
says **Engine running**. Then in Docker Desktop turn on
**Settings → General → "Start Docker Desktop when you sign in to your computer"**.

> Docker Desktop needs Windows 10 22H2 / Windows 11 23H2 or newer, and
> **virtualization enabled** (Task Manager → Performance → CPU → "Virtualization:
> Enabled"). It is free for personal use.

## 2. Add your Google key

Put your **`client_secret.json`** in this folder, next to `docker-start.cmd`.

```
qr-file-share-kit\
├── docker-start.cmd        ← step 3
├── client_secret.json      ← YOU ADD THIS
└── (everything else)       ← do not change
```

It is the same key file you use on your other laptop — it works on any laptop.

## 3. Start

**Double-click `docker-start.cmd`.** The first time it takes a minute while it loads
the app into Docker. Your browser opens by itself.

## 4. Sign in

Copy the **Admin token** shown in the black window and paste it into the browser.

## 5. Connect Google Drive (first time on this laptop)

Click **Connect Google Drive** → **Continue to Google** → choose your account. If
Google says *"Google hasn't verified this app"*, click **Advanced → Go to QR File
Share** (it is your own app) → **Allow**.

**Done.** From now on the app is always running in the background. Open
`http://localhost:8000/admin` whenever you need a QR code.

---

## Good to know

- **Stop the app:** double-click `docker-stop.cmd`. Nothing is deleted.
- **Travelling:** set the laptop's clock to the new time zone, then double-click
  `docker-start.cmd` once.
- **Google asks you to sign in again about once a week** — click **Reconnect Google
  Drive** when the app asks.
- **This laptop has its own list of QR codes.** QR codes made on another laptop are
  managed there.
- **Updating to a newer kit:** unzip the new kit **over** this folder (keep `.env` and
  `client_secret.json`), then double-click `docker-start.cmd`. Your QR codes are kept.

## If something goes wrong

| Problem | Fix |
|---|---|
| "Docker Desktop is not running" | Start Docker Desktop, wait for **Engine running**, try again. |
| "client_secret.json is missing" | Put the key file next to `docker-start.cmd` (step 2). |
| "This laptop's processor is not supported" | The kit supports Intel, AMD and ARM 64-bit laptops only. |
| Google says **"Access blocked"** | Your Gmail is not a test user in Google Cloud. Add it (Google Auth Platform → Audience → Test users). |
| The app warns the time zone is wrong | Double-click `docker-start.cmd` once. |
