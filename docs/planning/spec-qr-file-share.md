# Spec — QR-Based Secure File Delivery (Phase 1)

- **Status:** APPROVED 2026-09-20 — IMPLEMENTED. See [../qr-file-share.md](../qr-file-share.md).
- **Author:** Claude (Opus 5), on behalf of Wajahat Ahmed
- **Date:** 2026-09-19
- **Scope:** QR generation + scan-to-file delivery only. Quotation/report *generation* is Phase 2 and is explicitly out of scope here.

---

## 1. Context and origin

The request came from a real-world artifact: `90374749.pdf`, a ZATCA Phase-2 Saudi tax
invoice, which carries a QR code. The initial assumption was that this QR links to the
PDF. **It does not.**

Decoding it yields a 385-byte base64 TLV payload — the ZATCA e-invoicing standard:

| Tag | Field | Value |
|-----|-------|-------|
| 1 | Seller name | شركة عبد الله ابونيان التجارية \| ABDULLAH ABUNAYYAN TRADING COMPANY |
| 2 | VAT number | 311021826410003 |
| 3 | Timestamp | 2026-06-17T15:41:53 |
| 4 | Total incl. VAT | 1201.12 |
| 5 | VAT amount | 156.67 |
| 6 | Invoice XML hash | `IOc/mTB8HjpLoTceXP3q8IPJslhbLOM141Rhg3wyOSg=` |
| 7 | ECDSA signature | `MEUCIGVI9nvdt8nUhx5xx96kYq1odUfq...` |
| 8 | Public key | `3059301306072a8648ce3d0201...` (secp256r1) |

The PDF contains **no URLs and no link annotations**. That QR is a cryptographic tax
stamp for offline verification, not a file pointer.

**Consequence for this project:** the system we are building is unrelated to ZATCA. It
encodes a URL. The two must not be conflated in design discussions or documentation.
If ZATCA-compliant invoices are ever issued by this system, that is a separate,
regulated workstream.

---

## 2. State BEFORE this change

- Project directory contains four PDFs and nothing else. No code, no git repository,
  no dependencies, no documentation.
- No mechanism exists to share a file via QR.
- Current manual process (assumed): a quotation PDF is emailed or sent over WhatsApp
  as an attachment. No delivery tracking, no expiry, no revocation.

Test fixtures present in the project root:

| File | Pages | Character |
|------|-------|-----------|
| `90374749.pdf` | 3 | Tax invoice, 403 KB, image-heavy, embedded QR |
| `AI-Developer-WajahatAhmed-CV.pdf` | 2 | 68 KB, text + layout |
| `Wajahat-Ahmed_Zynvex_Cover-Letter.pdf` | 1 | 191 KB |
| `WajahatAhmed--CV.pdf` | 3 | 141 KB |

---

## 3. State AFTER this change

A running FastAPI service where an operator uploads a PDF and receives a PNG QR code.
Scanning that QR on any phone downloads the PDF — subject to expiry, revocation, and a
download cap. Every scan is logged.

```
┌──────────┐  upload   ┌─────────────────┐  store    ┌──────────────┐
│ Operator │──────────▶│  FastAPI app    │──────────▶│ Google Drive │
└──────────┘           │                 │           │  (private)   │
     ▲                 │  token ─┐       │           └──────────────┘
     │  QR.png         │         ▼       │                   ▲
     └─────────────────│    SQLite       │                   │ service
                       │   links table   │                   │ account
                       └─────────────────┘                   │
                                ▲                            │
┌──────────┐  scan             │  validate + log             │
│ Customer │───────────────────┴─────── stream PDF ──────────┘
│  phone   │
└──────────┘
```

### Decisions taken

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Storage = Google Drive, private, via service account | User's choice. No object-storage bill; Drive handles durability and virus scanning. |
| D2 | Files are **never** link-shared publicly | A public Drive link bypasses all expiry/revocation logic, making those controls theatre. |
| D3 | App **streams** bytes; does not 302-redirect | Follows from D2. Cost: app bandwidth (negligible at quotation sizes, <1 MB). |
| D4 | QR encodes a short app-owned token URL | Enables repointing an already-printed QR, short QR strings, and audit logging. |
| D5 | Token = 128-bit `secrets.token_urlsafe(16)` | ~22 chars, unguessable. Full URL ≈ 35 chars → low-density QR that scans reliably. |
| D6 | Metadata store = SQLite (Phase 1) | Single-writer, low volume. Postgres migration path noted in §8. |
| D7 | Stack = Python 3.13 + FastAPI | User's choice; aligns with Phase 2 PDF generation (WeasyPrint/ReportLab). |
| D8 | Each file version gets its own immutable token | A corrected quotation must not silently change under an issued QR. |

### Data model

```sql
CREATE TABLE links (
    token         TEXT PRIMARY KEY,        -- secrets.token_urlsafe(16)
    drive_file_id TEXT NOT NULL,
    filename      TEXT NOT NULL,
    content_type  TEXT NOT NULL DEFAULT 'application/pdf',
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,           -- integrity check on retrieval
    created_at    TEXT NOT NULL,           -- ISO-8601 UTC
    expires_at    TEXT,                    -- NULL = no expiry
    max_downloads INTEGER,                 -- NULL = unlimited
    download_count INTEGER NOT NULL DEFAULT 0,
    revoked_at    TEXT,                    -- NULL = active
    label         TEXT                     -- operator-facing note, e.g. "Quotation 4130334 v1"
);

CREATE TABLE access_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    token      TEXT NOT NULL REFERENCES links(token),
    accessed_at TEXT NOT NULL,
    ip         TEXT,
    user_agent TEXT,
    outcome    TEXT NOT NULL   -- served | expired | revoked | exhausted | not_found
);
```

`access_log` records **failed** attempts too — that is what makes it useful for
spotting a leaked QR being probed.

### API surface

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/files` | Upload PDF (multipart) + optional `expires_in_days`, `max_downloads`, `label`. Returns `{token, url, qr_png_base64}`. |
| `GET` | `/d/{token}` | **Public.** Validate → log → stream PDF, or render an HTML error page. |
| `GET` | `/api/files/{token}` | Metadata + download count. Admin. |
| `POST` | `/api/files/{token}/revoke` | Immediate kill switch. Admin. |
| `GET` | `/api/files/{token}/qr.png` | Re-fetch the QR image. Admin. |
| `GET` | `/api/files/{token}/log` | Access history. Admin. |
| `GET` | `/healthz` | Liveness. |

Admin endpoints are protected by a static bearer token from env in Phase 1
(see §8 for why that is a deliberate, time-boxed shortcut).

### Failure behaviour

`/d/{token}` never leaks whether a token existed. Expired, revoked, exhausted, and
unknown all return **HTTP 404** with a neutral human-readable page: *"This link is no
longer available. Please contact your sales representative."* The precise reason goes
to `access_log`, not to the visitor.

### Proposed layout

```
file_qr/
├── app/
│   ├── main.py          # FastAPI app + routes
│   ├── config.py        # pydantic-settings, env-driven
│   ├── db.py            # SQLite schema + queries
│   ├── storage.py       # Drive service-account client (Protocol-based)
│   ├── qr.py            # QR generation
│   └── templates/       # error + admin pages
├── tests/
│   ├── test_qr.py
│   ├── test_tokens.py
│   ├── test_access_rules.py
│   ├── test_api.py
│   └── test_e2e_scan.py
├── docs/
│   ├── planning/spec-qr-file-share.md   # this file
│   └── qr-file-share.md                 # feature docs, written with the code (Rule 5)
├── samples/             # the four test PDFs, moved here
├── .env.example
└── requirements.txt
```

`storage.py` is defined against a `Storage` Protocol with two implementations:
`LocalDiskStorage` (for tests, no network) and `GoogleDriveStorage`. This keeps the
test suite fast and offline, and leaves a clean seam if Drive is ever swapped for S3.

---

## 4. Test plan (Rules 6, 8, 10)

Unit:
- Token generation — uniqueness across 100k draws, URL-safe charset, length.
- QR round-trip — generate for each of the four sample PDFs' URLs, decode with
  `pyzbar`, assert the decoded string equals the input exactly.
- Expiry logic — boundary cases at T-1s, T, T+1s.
- Download cap — the Nth download succeeds, N+1 fails.
- Revocation — takes effect immediately, including mid-session.

Integration:
- Upload → QR → scan → byte-for-byte identical PDF returned (`sha256` match) for all
  four fixtures, including the 403 KB invoice.
- All four failure modes return 404 with an identical body; `access_log` records the
  true distinct reason for each.
- Concurrent downloads against `max_downloads=1` — exactly one succeeds. This is a
  genuine race in SQLite and needs the counter increment inside the transaction that
  reads it.

End-to-end (manual, once):
- Render the QR, scan with a real phone on mobile data (not Wi-Fi — proves the URL is
  genuinely public), confirm the PDF opens in the phone's viewer.

---

## 5. Security review

| Risk | Mitigation |
|------|-----------|
| Leaked/forwarded QR | Expiry + download cap + revocation + access log. Accepted residual: within the validity window, anyone holding the QR can fetch. |
| Token brute force | 128 bits of entropy. Rate-limit `/d/` per IP. |
| Enumeration via error messages | Uniform 404 for all failure modes. |
| Drive credential leak | Service-account JSON from env/secret store, never committed. `.gitignore` from the first commit. |
| Malicious upload | Admin-only endpoint; validate magic bytes are `%PDF`; cap size at 25 MB. |
| PII in logs | Log truncated IP (`/24`), not full. Retain 90 days. |

**Residual risk requiring sign-off:** a quotation fetched during the validity window
can be saved and redistributed freely. No link-based scheme can prevent this. If
prices must be protected beyond delivery, that requires a gated flow (OTP/PO-number
challenge) — available as a later phase, noted in §8.

---

## 6. What this phase does NOT include

- Quotation/report generation (Phase 2).
- Any ZATCA compliance, signing, or invoice-stamping.
- A user-facing admin UI — Phase 1 is API + a minimal HTML page.
- Multi-user accounts, roles, or SSO.
- Custom domain / branded short link.

---

## 7. Estimate

| Step | Effort |
|------|--------|
| Scaffold, config, SQLite schema | S |
| QR generation + tests | S |
| Drive service-account storage + local test double | M |
| API routes, access rules, logging | M |
| Test suite | M |
| Feature docs (Rule 5) | S |

Deliverable: a locally runnable service passing its full suite. Public deployment is a
separate step needing a hosting decision and a domain.

---

## 8. Open questions for the user

1. **Google account tier.** Personal Gmail or Google Workspace? Workspace allows
   service-account domain-wide delegation and shared drives; personal Gmail needs the
   files owned by the service account itself, which complicates manual inspection.
   Alternatively — confirm Dropbox instead, which uses a simpler app-token model.
2. **Hosting for the public URL.** The QR is useless until the app has a public
   HTTPS address. Render/Fly/Railway free tier, a company VM, or somewhere else?
   Note that free tiers cold-start, adding ~10–30 s to the first scan — poor look in
   front of a customer.
3. **Default expiry.** Proposing 30 days, unlimited downloads, overridable per upload.
   Confirm or set your own.
4. **Admin auth.** Phase 1 proposes a static bearer token in env — adequate for a
   single operator on a private URL, inadequate the moment a second person needs
   access. Is single-operator correct for now?
5. **Volume.** Roughly how many quotations per month? Under ~1000 validates SQLite;
   materially above that, I'd start on Postgres rather than migrate later.

---

## 9. Approval

Per Working Contract Rule 9, no code will be written until this spec is reviewed and
explicitly approved.

- [x] Approved by Wajahat — 2026-09-20

### Implementation notes (post-build)

Built as specced, with two deviations worth recording:

1. **`check_same_thread=False` on SQLite connections.** Not anticipated in the spec.
   FastAPI runs sync generator dependencies in a worker thread while `async def`
   routes run on the event loop, so a connection is legitimately created and used
   from different threads. Safe here because connections are per-request and never
   used concurrently; both invariants are documented at the call site in `app/db.py`.

2. **`no_expiry` upload flag added.** The spec had no way to express "permanent link"
   distinctly from "use the default", since `expires_in_days=None` already means the
   latter. One boolean form field, no schema change.

Open questions 1 (Drive account tier) and 2 (hosting) remain unanswered and are not
blocking: the build runs on `LocalDiskStorage` and the whole suite is offline. The
Drive backend is implemented but unverified against live Drive.
