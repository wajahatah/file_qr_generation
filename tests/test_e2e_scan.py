"""End-to-end: upload -> render QR -> DECODE THE QR -> fetch -> compare bytes.

The decode step is the point. Asserting on the token the API handed back would prove
nothing about the image a customer actually points a phone at; these tests read the
token out of the rendered pixels, exactly as a phone camera would.
"""

from __future__ import annotations

import base64
import hashlib
import io

from PIL import Image
from pyzbar.pyzbar import decode

from app import db
from tests.conftest import AUTH


def scan(qr_png_base64: str) -> str:
    """Decode a QR image the way a phone would, returning the URL it encodes."""
    img = Image.open(io.BytesIO(base64.b64decode(qr_png_base64)))
    results = decode(img)
    assert len(results) == 1, f"expected exactly one QR, found {len(results)}"
    return results[0].data.decode("utf-8")


def upload(client, path, **form):
    with open(path, "rb") as fh:
        return client.post(
            "/api/files",
            headers=AUTH,
            files={"file": (path.name, fh, "application/pdf")},
            data=form,
        )


def test_every_sample_pdf_survives_the_full_round_trip(client, sample_pdfs) -> None:
    """All four fixtures: 1, 2 and 3 page; text-heavy and image-heavy; 68 KB to 403 KB."""
    assert len(sample_pdfs) == 4, "expected the four sample PDFs"

    for pdf in sample_pdfs:
        original = pdf.read_bytes()

        body = upload(client, pdf).json()
        scanned_url = scan(body["qr_png_base64"])

        # The URL in the pixels must be the URL the API reported.
        assert scanned_url == body["url"]

        token = scanned_url.rsplit("/d/", 1)[1]
        r = client.get(f"/d/{token}")

        assert r.status_code == 200, pdf.name
        assert r.content == original, f"{pdf.name}: bytes differ after round trip"
        assert hashlib.sha256(r.content).hexdigest() == hashlib.sha256(original).hexdigest()
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")


def test_stored_hash_matches_the_delivered_bytes(client, invoice_pdf, conn) -> None:
    """The sha256 column is an integrity record, so it had better be right."""
    token = upload(client, invoice_pdf).json()["token"]
    delivered = client.get(f"/d/{token}").content
    row = db.get_link(conn, token)
    assert row["sha256"] == hashlib.sha256(delivered).hexdigest()
    assert row["size_bytes"] == len(delivered)


def test_largest_sample_streams_intact(client, invoice_pdf) -> None:
    """403 KB across 64 KB chunks -- catches an off-by-one in the chunking loop."""
    original = invoice_pdf.read_bytes()
    assert len(original) > 6 * 65536, "fixture no longer exercises multi-chunk streaming"
    token = upload(client, invoice_pdf).json()["token"]
    r = client.get(f"/d/{token}")
    assert len(r.content) == len(original)
    assert r.content == original


def test_the_delivered_invoice_still_contains_its_own_zatca_qr(client, invoice_pdf) -> None:
    """Delivery must be byte-exact, not a re-render.

    The invoice carries its own ZATCA tax QR. If our pipeline ever re-encoded or
    recompressed the PDF, that embedded QR would be the first casualty -- and an
    invoice whose tax stamp no longer decodes is legally worthless.
    """
    from pypdf import PdfReader

    token = upload(client, invoice_pdf).json()["token"]
    delivered = client.get(f"/d/{token}").content

    reader = PdfReader(io.BytesIO(delivered))
    assert len(reader.pages) == 3

    pngs = [
        img.data
        for page in reader.pages
        for img in page.images
        if img.data.startswith(b"\x89PNG")
    ]
    assert pngs, "the embedded ZATCA QR image is missing from the delivered file"

    img = Image.open(io.BytesIO(pngs[0])).convert("L")
    # The source PDF ships this QR without a quiet zone, so pad one on to decode it.
    padded = Image.new("L", (img.width + 80, img.height + 80), 255)
    padded.paste(img, (40, 40))
    results = decode(padded)
    assert results, "the delivered invoice's ZATCA QR no longer decodes"

    payload = base64.b64decode(results[0].data)
    assert payload[0] == 1, "expected ZATCA TLV tag 1 (seller name) first"
    assert b"311021826410003" in payload, "seller VAT number missing from the tax stamp"


def test_a_scanned_link_dies_exactly_when_told_to(client, invoice_pdf) -> None:
    """The full operator story: issue, customer scans, operator revokes, scan fails."""
    body = upload(client, invoice_pdf, max_downloads=2, label="Quotation 4130334 v1").json()
    token = scan(body["qr_png_base64"]).rsplit("/d/", 1)[1]

    assert client.get(f"/d/{token}").status_code == 200  # customer opens it
    client.post(f"/api/files/{token}/revoke", headers=AUTH)  # operator kills it
    assert client.get(f"/d/{token}").status_code == 404  # same QR, now dead

    log = client.get(f"/api/files/{token}/log", headers=AUTH).json()
    assert log["served"] == 1
    assert log["attempts"] == 2
    assert log["entries"][0]["outcome"] == db.OUTCOME_REVOKED


def test_two_versions_of_a_quotation_get_independent_tokens(client, sample_pdfs) -> None:
    """Spec decision D8: a corrected quotation must not change under an issued QR."""
    v1, v2 = sample_pdfs[0], sample_pdfs[1]
    t1 = upload(client, v1, label="Quotation 4130334 v1").json()["token"]
    t2 = upload(client, v2, label="Quotation 4130334 v2").json()["token"]

    assert t1 != t2
    assert client.get(f"/d/{t1}").content == v1.read_bytes()
    assert client.get(f"/d/{t2}").content == v2.read_bytes()

    # Retiring v1 must leave v2 untouched.
    client.post(f"/api/files/{t1}/revoke", headers=AUTH)
    assert client.get(f"/d/{t1}").status_code == 404
    assert client.get(f"/d/{t2}").status_code == 200


def test_the_same_file_uploaded_twice_gets_distinct_tokens(client, invoice_pdf) -> None:
    a = upload(client, invoice_pdf).json()["token"]
    b = upload(client, invoice_pdf).json()["token"]
    assert a != b
    client.post(f"/api/files/{a}/revoke", headers=AUTH)
    assert client.get(f"/d/{b}").status_code == 200, "revoking one must not affect the other"
