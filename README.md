# QR File Share

Turn a PDF into a QR code. Anyone who scans it opens the PDF from **your Google
Drive** — even when this laptop is off. Every QR code has a **time limit** you choose;
when it runs out, the app removes the file from sharing.

Built for sending quotations: drop in the PDF, pick how long it should work, send or
print the QR code. Extend it, end it, or bring it back later — without ever reprinting
the QR code.

## Run it

**New here? Read [HOW-TO-RUN.md](HOW-TO-RUN.md)** — short, simple steps: what to add,
where to put it, and how to start the app.

In short: put your Google key file `client_secret.json` next to `start.cmd`, then
double-click **`start.cmd`**. The app opens in your browser.

**Or with Docker:** double-click **`docker-start.cmd`** instead — it runs in the
background and starts with Docker Desktop. See HOW-TO-RUN.md, "Run with Docker".

**On another laptop:** `make-kit.cmd` makes one zip with the app ready-built; unzip
it there, add `client_secret.json`, double-click `docker-start.cmd`. See the setup
guide, §10.

## Documentation

- **[HOW-TO-RUN.md](HOW-TO-RUN.md)** — start here: the quick, simple version.
- **[docs/setup-guide.md](docs/setup-guide.md)** — the full guide: setup, making QR codes,
  time limits, managing them, troubleshooting.
- **[docs/qr-file-share.md](docs/qr-file-share.md)** — technical: architecture, how
  limits are enforced, security, API, tests.
- **[docs/planning/spec-admin-ui.md](docs/planning/spec-admin-ui.md)** — the approved
  design and the decisions behind it.

## Tests

```
.venv\Scripts\python.exe -m pytest
```

310 tests, all offline — Google Drive is replaced by an in-memory stand-in.

## Layout

```
start.cmd        one-click launcher
docker-start.cmd one-click launcher, Docker (+ docker-stop.cmd)
make-kit.cmd     builds the portable kit zip for another laptop
Dockerfile       image; compose.yaml runs it
HOW-TO-RUN.md    quick guide
app/
  main.py        app, API, removal sweep
  admin.py       pages
  service.py     issue / change / end / reactivate / sweep
  limits.py      time-limit logic
  drive.py       Google Drive client
  tokens.py      where the Google sign-in is kept
  timezone.py    which time zone limits use
  db.py          SQLite
  templates/     HTML
  static/        JS, CSS, icons
tests/           310 tests; fakes.py; run_fake_server.py
tools/           start.cmd helper; make_kit.py; kit/ (kit compose + START-HERE)
samples/         test PDFs
```

## History

Phase 1 served files from the laptop itself. It was replaced by Google Drive delivery
so QR codes keep working with the laptop off. It is preserved at git tag
`phase-1-laptop-delivery`.

## Note

`samples/90374749.pdf` carries its own QR code. That one is a ZATCA tax stamp — signed
invoice data for tax verification, not a link — and is unrelated to this app.
