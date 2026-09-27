# QR File Share — Feature Documentation

Generate a QR code that delivers a PDF, with expiry, download caps, revocation and an
access log.

Implements [`docs/planning/spec-qr-file-share.md`](planning/spec-qr-file-share.md).

---

## 1. What it does

```
┌──────────┐  POST /api/files   ┌─────────────────┐   save    ┌──────────────┐
│ Operator │───────────────────▶│  FastAPI app    │──────────▶│   Storage    │
└──────────┘                    │                 │           │ local | Drive│
     ▲                          │  token ─┐       │           └──────────────┘
     │  QR png + url            │         ▼       │                   ▲
     └──────────────────────────│    SQLite       │                   │
                                │  links + log    │                   │
                                └─────────────────┘                   │
                                         ▲                            │
┌──────────┐  GET /d/{token}             │  validate + log            │
│ Customer │─────────────────────────────┴───── stream bytes ─────────┘
│  phone   │
└──────────┘
```

The QR encodes **our** short URL (`https://host/d/<token>`, ~35 chars), never the file
and never a third-party storage link. That indirection is what makes expiry,
revocation, download counting and repointing a printed QR possible at all.

## 2. Quick start

```
start.cmd
```

First run creates the virtual environment, installs dependencies and writes a `.env`
with a generated admin token. `start.cmd lan` binds to the local network so a real
phone can scan. Full walkthrough, including Google Drive setup, in the
[setup guide](setup-guide.md).

### Issue a QR

```bash
curl -X POST http://localhost:8000/api/files \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "file=@samples/90374749.pdf" \
  -F "expires_in_days=7" \
  -F "max_downloads=2" \
  -F "label=Quotation 4130334 v1"
```

```json
{
  "token": "PGhI54DnFK5Q6UO7VRlAtA",
  "url": "http://localhost:8000/d/PGhI54DnFK5Q6UO7VRlAtA",
  "filename": "90374749.pdf",
  "expires_at": "2026-09-26T22:20:46+00:00",
  "max_downloads": 2,
  "qr_png_base64": "iVBORw0KGgo..."
}
```

Save the QR straight to a file:

```bash
curl -s "http://localhost:8000/api/files/$TOKEN/qr.png" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -o quotation-qr.png
```

## 3. Configuration

All values are environment variables; see `.env.example`.

| Variable | Default | Notes |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | **The origin baked into every QR.** Must be the public HTTPS origin in production. |
| `ADMIN_TOKEN` | `dev-admin-token-change-me` | Bearer token for all `/api/` routes. Change it. |
| `STORAGE_BACKEND` | `local` | `local` or `drive`. |
| `STORAGE_DIR` | `./storage` | Used when backend is `local`. |
| `DRIVE_FOLDER_ID` | — | Used when backend is `drive`. |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `./service-account.json` | Used when backend is `drive`. |
| `DRIVE_SCOPE` | `.../auth/drive.file` | Widen to `.../auth/drive` only if uploads 404 on the folder. |
| `DB_PATH` | `./file_qr.db` | SQLite file. |
| `DEFAULT_EXPIRY_DAYS` | `30` | Applied when an upload specifies nothing. |
| `MAX_UPLOAD_BYTES` | `26214400` (25 MB) | Hard cap. |
| `LOG_RETENTION_DAYS` | `90` | Used by the purge endpoint. |

> `BASE_URL` is the one setting that is expensive to get wrong. It is captured into
> every QR image at generation time. Changing it later does **not** fix QR codes that
> have already been printed or sent — those keep pointing at the old origin.

## 4. API

### Public

| Method | Path | Notes |
|---|---|---|
| `GET` | `/d/{token}` | Validate → log → stream. No auth. This is what the QR points at. |
| `GET` | `/healthz` | Liveness. |

### Admin (all require `Authorization: Bearer <ADMIN_TOKEN>`)

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/files` | Multipart upload. Fields: `file`, `expires_in_days`, `max_downloads`, `label`, `no_expiry`. |
| `GET` | `/api/files` | All links, newest first. |
| `GET` | `/api/files/{token}` | Metadata + live status + download count. |
| `GET` | `/api/files/{token}/qr.png` | Re-render the QR. |
| `POST` | `/api/files/{token}/revoke` | Immediate kill switch. |
| `GET` | `/api/files/{token}/log` | Access history. |
| `POST` | `/api/maintenance/purge-logs` | Delete log rows older than `LOG_RETENTION_DAYS`. |

Upload rejections: `400` empty or nonsensical limits, `413` over size cap, `415` not a
PDF (checked by magic bytes, not by file extension), `401` bad or missing token.

## 5. Access rules

A scan is served only when **all** of these hold:

1. the token exists;
2. it has not been revoked;
3. `expires_at` is `NULL` or strictly in the future;
4. `max_downloads` is `NULL` or `download_count < max_downloads`.

Anything else returns **404** with `app/templates/unavailable.html`.

### The uniform-404 guarantee

Expired, revoked, exhausted and never-existed all produce a **byte-identical** page.
The real reason is written only to `access_log`.

This is deliberate. Distinguishable errors turn any single leaked QR into an oracle:
an attacker who can tell "expired" from "no such token" can enumerate which tokens are
real. `tests/test_api.py::test_all_failure_modes_are_externally_indistinguishable`
asserts the response bodies are identical and that the page never names the reason —
so a future "let's be more helpful to the user" edit fails the suite rather than
quietly reopening the hole.

### Expiry boundary

`expires_at` is inclusive: at exactly `T` the link is already expired. All timestamps
are stored as fixed-format UTC ISO-8601, which makes lexicographic string comparison
correct — do not change the timestamp format without revisiting `db.classify`.

### Concurrency

`db.try_consume_download` is a single conditional `UPDATE`, not a read-then-write:

```sql
UPDATE links SET download_count = download_count + 1
 WHERE token = ? AND revoked_at IS NULL
   AND (expires_at IS NULL OR expires_at > ?)
   AND (max_downloads IS NULL OR download_count < max_downloads)
```

`db.classify` is advisory only — used for logging the true reason and for the metadata
endpoint. The `UPDATE` is the sole authority on whether a download may proceed, and it
re-checks every condition.

With `max_downloads = 1` and twenty simultaneous scans, exactly one wins. A
read-then-write implementation passes every other test in the suite and fails
`test_concurrent_downloads_respect_a_cap_of_one`.

### SQLite threading

Connections are opened with `check_same_thread=False` because FastAPI runs sync
generator dependencies in a worker thread while `async def` routes run on the event
loop. This is safe **only** while two invariants hold:

1. one connection per request — never shared between requests;
2. accesses within a request are strictly sequential, never concurrent.

Both are enforced by `get_conn` in `app/main.py`. Any change to the request path must
preserve them.

## 6. Storage backends

`app/storage.py` defines a `Storage` Protocol with two implementations.

**`LocalDiskStorage`** (default). Blobs are written to a temp name and `replace()`d
into place, so a reader can never observe a half-written file. Storage refs are
uuid4 hex and validated against path traversal.

**`GoogleDriveStorage`**. Service-account credentials, scope `drive.file`.

> Drive files are **never** link-shared. The service reads them with its own
> credentials and streams the bytes. A public Drive link would be reachable
> independently of this service, which would make expiry and revocation decorative —
> anyone who captured the final URL could bypass every rule above. This is spec
> decision D2/D3 and is the reason the app streams rather than redirects.

The whole test suite runs against `LocalDiskStorage`, so it needs no network and no
Google credentials.

## 7. Privacy

Caller IPs are truncated before storage: `/24` for IPv4, `/64` for IPv6. Enough to
notice a leaked QR being hit from somewhere unexpected; not enough to identify an
individual. `POST /api/maintenance/purge-logs` drops rows past `LOG_RETENTION_DAYS`
(default 90) and should be run on a schedule.

## 8. Tests

```bash
.venv/Scripts/python.exe -m pytest
```

81 tests, all offline.

| File | Covers |
|---|---|
| `test_qr.py` | QR round-trip fidelity, quiet zone, payload length |
| `test_tokens.py` | Entropy, charset, 100k-draw uniqueness, non-sequentiality |
| `test_access_rules.py` | Expiry boundaries, download caps, revocation, the concurrency race, log purge |
| `test_api.py` | Auth, upload validation, the uniform-404 guarantee, admin endpoints |
| `test_e2e_scan.py` | Upload → **decode the QR image** → fetch → byte comparison |
| `test_launcher.py` | `start.cmd`'s BASE_URL resolution and first-run bootstrap |

The end-to-end tests decode the rendered QR with `pyzbar` — a different library from
the `qrcode` one that generates it — and extract the token from the decoded pixels
rather than from the API response. Asserting on the token the API handed back would
prove nothing about the image a customer actually points a phone at.

`test_the_delivered_invoice_still_contains_its_own_zatca_qr` additionally decodes the
ZATCA tax QR embedded *inside* the delivered invoice. If the pipeline ever re-encoded
or recompressed a PDF, that embedded stamp would be the first casualty, and an invoice
whose tax stamp no longer decodes is legally worthless.

## 9. A note on the ZATCA QR

The invoice that prompted this project (`samples/90374749.pdf`) carries its own QR.
**It is not a link and this system has nothing to do with it.** It is a 385-byte
base64 TLV payload defined by Saudi e-invoicing regulation: seller name, VAT number,
timestamp, total, VAT amount, invoice XML hash, ECDSA signature, public key. Scanning
it yields data for offline tax verification, not a download.

Do not conflate the two. If ZATCA-compliant invoices ever need to be *issued* by this
system, that is a separate regulated workstream, not an extension of this feature.

One practical lesson did carry over: that QR ships with **no quiet zone**, and OpenCV
could not decode it until white padding was added back. `app/qr.py` therefore always
renders a 4-module border, and `test_quiet_zone_is_present` pins it.

## 10. Deploying

The QR is inert until the app has a public HTTPS origin.

1. Deploy behind TLS; set `BASE_URL` to that origin **before** issuing any QR.
2. Set a strong `ADMIN_TOKEN`.
3. Put a rate limit on `/d/` at the reverse proxy — the app does not rate-limit itself.
4. If behind a proxy, run uvicorn with `--proxy-headers` so `access_log.ip` records the
   real caller rather than the proxy.
5. Schedule `POST /api/maintenance/purge-logs`.
6. Back up `DB_PATH`. Losing it orphans every blob and breaks every QR in circulation —
   the tokens live only there.

### Known limitations

- **Single admin token.** No per-user accounts or audit of *who* issued a link.
- **No rate limiting in-app.** Delegated to the reverse proxy.
- **SQLite.** Fine to roughly 1k links/month; beyond that, move to Postgres.
- **Anyone who opens a document inside its validity window can save and forward it.**
  No link-based scheme prevents this. Protecting content past delivery needs a gated
  flow (OTP or PO-number challenge), which is out of scope here.
