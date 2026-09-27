# QR File Share

Generate a QR code that delivers a PDF. Scanning it downloads the document — subject
to expiry, a download cap, and revocation, with every scan logged.

Built for sending quotations to customers: issue a QR, send it, see when it was
opened, kill the link when the quote is superseded.

## Run it

```
start.cmd
```

That is all. First run creates the virtual environment, installs dependencies and
generates an admin token; later runs reuse them. Then open
<http://localhost:8000/docs>.

| Command | Result |
|---|---|
| `start.cmd` | localhost:8000 |
| `start.cmd lan` | binds to your Wi-Fi so a **phone can scan the QR** |
| `start.cmd 9000` | different port |

Tests: `.venv\Scripts\python.exe -m pytest` (81 tests, all offline).

```bash
curl -X POST http://localhost:8000/api/files \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@samples/90374749.pdf" \
  -F "expires_in_days=7" -F "max_downloads=2" \
  -F "label=Quotation 4130334 v1"
```

Returns a token, a URL, and the QR as a base64 PNG.

## Documentation

- **[docs/setup-guide.md](docs/setup-guide.md)** — start here: running it, scanning
  from a phone, and where to put your Google Drive service account key and folder ID.
- **[docs/qr-file-share.md](docs/qr-file-share.md)** — feature docs: API, access rules,
  storage backends, deployment, limitations.
- **[docs/planning/spec-qr-file-share.md](docs/planning/spec-qr-file-share.md)** — the
  approved design and the decisions behind it.

## Layout

```
start.cmd       one-click launcher
app/
  main.py       FastAPI routes
  db.py         SQLite: links + access log
  storage.py    Storage Protocol; local disk and Google Drive backends
  qr.py         QR rendering
  config.py     env-driven settings
tests/          81 tests
tools/          launcher helper
samples/        test fixtures
```

## Not included

Quotation/report **generation** is Phase 2. This phase delivers an existing PDF via QR;
it does not create the document.

## Note

`samples/90374749.pdf` carries its own QR code. That one is a ZATCA tax stamp — signed
invoice data for offline verification, not a link — and is unrelated to this system.
See §9 of the feature docs.
