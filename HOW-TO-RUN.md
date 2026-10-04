# How to Run — Quick Guide

Simple steps to get the app working. For more detail, see
[docs/setup-guide.md](docs/setup-guide.md).

---

## What this app does

1. You give it a PDF.
2. It puts the PDF in your Google Drive and gives you a QR code.
3. Anyone who scans the QR code with their phone gets the PDF.
4. The QR code stops working after the time you choose (for example, 7 days).

The QR code keeps working even when your laptop is off.

---

## What you need

- A Windows laptop
- Internet
- A Google account (normal Gmail is fine)
- Python — download from <https://www.python.org/downloads/>.
  **When installing, tick the box "Add python.exe to PATH".**

---

## Step 1 — Put the app folder on the laptop

Copy the whole app folder to the laptop, for example to `C:\QR File Share`.

> **Important:** if you copied it from another computer, **delete the `.venv` folder**
> inside it. That folder only works on the computer that made it. The app makes a
> new one by itself.

---

## Step 2 — Get your Google key file (one time only)

This lets the app use your Google Drive. You do it once. It takes about 10 minutes.

1. Go to <https://console.cloud.google.com/> and sign in with your Google account.
2. At the top, click the project list → **New Project** → name it `QR File Share` →
   **Create**.
3. Search for **Google Drive API** at the top → open it → click **Enable**.
4. Open the menu → **Google Auth Platform** → **Get started**:
   - App name: `QR File Share`
   - Email: your email
   - Audience: **External**
   - Agree and click **Create**
5. Click **Data Access** → **Add or remove scopes** → tick the one that ends in
   **`/auth/drive.file`** → **Update** → **Save**.
   On the **Branding** page, **do not upload a logo** — a logo makes Google ask for a
   review. Leave the home page, privacy policy and domain boxes empty.
6. Click **Audience**. Under **Test users**, click **Add users**, type **your own
   Gmail address** (the one whose Drive will hold the files), and click **Save**.
   **Leave the status as "Testing". Do not click Publish.** Publishing needs a
   website with a privacy policy, and you do not need it.
7. Click **Clients** → **Create client** → type **Desktop app** → **Create** →
   **Download JSON**.
8. Rename the downloaded file to exactly:

   ```
   client_secret.json
   ```

---

> **Once a week, Google asks you to sign in again.** This is normal while the app is
> in "Testing". The app shows **Reconnect Google Drive** — click it, sign in, done.

---

## Step 3 — Put the key file in the right place

Put `client_secret.json` in the app folder, **next to `start.cmd`**:

```
QR File Share\
├── start.cmd              ← double-click this to run the app
├── client_secret.json     ← YOU ADD THIS (from Step 2)
├── .env                   ← made for you on first run — has your password
├── HOW-TO-RUN.md          ← this guide
└── (all other files)      ← do not change
```

**That is the only file you add.** Everything else is ready.

Keep `client_secret.json` private. Do not email or share it.

---

## Step 4 — Start the app

1. **Double-click `start.cmd`.**
2. A black window opens. The first time, wait about a minute while it sets itself up.
3. The black window shows your **Admin token** — a long password. Copy it.
4. Your browser opens the app. Paste the token and click **Sign in**.

> **Keep the black window open** while you use the app. Closing it stops the app.

**Lost the token?** Open the `.env` file in the app folder with Notepad. It is the
line starting with `ADMIN_TOKEN=`.

---

## Step 5 — Connect Google Drive (first time only)

1. In the app, click **Connect Google Drive**.
2. Google opens in your browser. Choose your account.
3. If you see **"Google hasn't verified this app"**: this is your own app, so it is
   safe. Click **Advanced** → **Go to QR File Share**.
4. Click **Allow**, then close that tab and go back to the app.

The top of the app now shows **Google Drive: your email**. The app remembers this —
you only do it once.

---

## Make a QR code

1. **Drop a PDF** into the box (or click the box to choose one).
2. Type a **label** if you want, for example `Quotation 4130334`. Only you see it.
3. Choose **how long it works**: **1 day**, **3 days**, **7 days**, **30 days**, or
   pick a date.
   The green line shows the exact last day, for example
   *"Customers can open this until Mon 5 Oct 2026, 11:59 PM"*.
4. Click **Create QR code**.

Then send it:

| Button | Use it to |
|---|---|
| **Copy image** | Paste the QR code into WhatsApp, email or Word |
| **Download PNG** | Save the QR code as a picture |
| **Print** | Print the QR code on paper |
| **Copy link** | Send the link as text instead |

---

## Change things later

All your QR codes are listed under **Issued QR codes**. For each one you can:

- **Change limit** — give more time or less time. The same QR code keeps working.
- **End now** — stop it right away.
- **Reactivate** — bring back an expired QR code (within 30 days).

To change the default time for new QR codes: **Settings** → **New QR codes last**.

---

## Every day after setup

1. Double-click `start.cmd`.
2. Sign in (you stay signed in for 12 hours).
3. Make QR codes.

That is all. Steps 1, 2, 3 and 5 are only done once.

---

## Run with Docker (optional)

Instead of `start.cmd`, you can run the app in **Docker**. Then it runs in the
background — no black window to keep open — and starts by itself with your laptop.

You need **Docker Desktop** installed and running. It is free for personal use.

**First time:**

1. Do Steps 2 and 3 above — `client_secret.json` must be next to `docker-start.cmd`.
2. **Double-click `docker-start.cmd`.** The first time takes a few minutes.
3. Your browser opens. Sign in with the **admin token** shown in the window.
4. Click **Connect Google Drive** → **Continue to Google** → sign in.
   Docker keeps its own Google sign-in, so do this once for Docker even if you
   already connected with `start.cmd`.

**Every day after that:** nothing to start. Just open `http://localhost:8000/admin`.
In Docker Desktop, turn on **Settings → General → "Start Docker Desktop when you sign
in to your computer"**, so the app is always ready.

**Travelling (for example to Riyadh):** set the laptop to the new time zone
(**Windows Settings → Time & language → Date & time**), then double-click
`docker-start.cmd` once. No rebuilding. If you forget, the app shows a warning.

**To stop it:** double-click `docker-stop.cmd`. Nothing is deleted.

### Putting it on another laptop

1. On this laptop, double-click **`make-kit.cmd`**. It makes one zip in the `dist`
   folder, for example `qr-file-share-kit-2026.10.04-6af9929.zip`.
2. Put that zip on GitHub as a **Release** (see the setup guide, §10), or copy it by
   USB or Google Drive.
3. On the other laptop: download and unzip it, put `client_secret.json` in the folder,
   and follow **`START-HERE.md`** inside — install Docker, then double-click
   `docker-start.cmd`.

The kit works on Intel, AMD and ARM laptops. It contains no passwords or keys.

> **Use one or the other — `start.cmd` or Docker, not both.** They keep separate lists
> of QR codes, and both use the same address, so they cannot run at the same time.

---

## Good to know

- **The customer's phone needs internet** to open the PDF.
- **Your laptop can be off** — the QR code still works.
- **Reconnect Google Drive when the app asks** (about once a week). Until you do,
  expired QR codes cannot be removed — the app shows a warning.
- **Expired QR codes are removed when the app is running.** If the laptop is off when
  the time runs out, the QR code works until you next start the app. Starting the app
  removes it straight away.

---

## If something goes wrong

| Problem | Fix |
|---|---|
| "Python was not found" | Install Python. Tick **"Add python.exe to PATH"**. |
| The app says **"Google Drive is not set up yet"** | `client_secret.json` is missing, or has a different name. Check Step 3. |
| **"It must be a 'Desktop app' client"** | In Step 2, item 7, choose **Desktop app** and download again. |
| Google says **"Access blocked"** or **"has not completed the Google verification process"** | Your email is not a test user. Do Step 2, item 6, with the same Gmail you sign in with. |
| The app asks to **reconnect Google Drive** | Normal — about once a week. Click **Connect Google Drive** and sign in. |
| **"Could not reach Google Drive"** | Check the internet, then try again. |
| The browser did not open | Go to `http://localhost:8000/admin` yourself. |
| **Docker:** "Docker Desktop is not running" | Start Docker Desktop, wait for "Engine running", run `docker-start.cmd` again. |
| **Docker:** warning that the time zone is wrong | Double-click `docker-start.cmd` once. |
| **Docker:** "port is already allocated" | The `start.cmd` black window is still open. Close it, then run `docker-start.cmd` again. |
| The black window shows an error and stops | Close it, delete the `.venv` folder, and double-click `start.cmd` again. |
| A customer says the QR code does not work | Find it in **Issued QR codes** and read its status. Use **Change limit** or **Reactivate**, or make a new one. |
