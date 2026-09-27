"""QR generation: the code we produce must decode back to exactly what went in.

These tests use pyzbar (a different library from the one that generates the code), so
a bug in `qrcode` cannot mask itself by being used on both sides.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from pyzbar.pyzbar import decode

from app.qr import download_url, make_qr_png


def decode_png(png: bytes) -> list[str]:
    img = Image.open(io.BytesIO(png))
    return [d.data.decode("utf-8") for d in decode(img)]


@pytest.mark.parametrize(
    "url",
    [
        "https://qr.test/d/abc123",
        "https://qr.example.com/d/xK9mP2qR7wL4nT8vB1cY5z",
        "http://localhost:8000/d/short",
        # Long host + long token: still must round-trip exactly.
        "https://quotations.abdullah-abunayyan-trading.com.sa/d/"
        + "A" * 22,
    ],
)
def test_qr_round_trips_exactly(url: str) -> None:
    decoded = decode_png(make_qr_png(url))
    assert decoded == [url], f"round-trip mismatch for {url}"


def test_qr_encodes_our_url_not_the_file(invoice_pdf) -> None:
    """Guard against ever regressing to embedding data like the ZATCA invoice QR."""
    url = download_url("https://qr.test", "tok123")
    decoded = decode_png(make_qr_png(url))[0]
    assert decoded.startswith("https://qr.test/d/")
    assert "PDF" not in decoded
    assert len(decoded) < 120, "QR payload should stay short so the code prints small"


def test_download_url_normalises_trailing_slash() -> None:
    assert download_url("https://qr.test/", "t") == "https://qr.test/d/t"
    assert download_url("https://qr.test", "t") == "https://qr.test/d/t"


def test_quiet_zone_is_present() -> None:
    """A QR without its 4-module quiet zone often fails to scan.

    This is not theoretical: the ZATCA invoice that started this project ships its QR
    with no quiet zone, and OpenCV could not decode it until one was padded back on.
    """
    png = make_qr_png("https://qr.test/d/abc", box_size=10, border=4)
    img = Image.open(io.BytesIO(png)).convert("L")
    w, h = img.size
    # The outer 40px (4 modules * box_size 10) must be entirely white.
    for x in range(w):
        for y in list(range(40)) + list(range(h - 40, h)):
            assert img.getpixel((x, y)) == 255


def test_border_zero_would_lose_the_quiet_zone() -> None:
    """Sanity check that the border parameter is actually wired through."""
    with_border = Image.open(io.BytesIO(make_qr_png("https://qr.test/d/abc")))
    without = Image.open(
        io.BytesIO(make_qr_png("https://qr.test/d/abc", border=0))
    )
    assert with_border.size[0] > without.size[0]
