"""QR rendering: the code must decode back to exactly the Drive link that went in.

Decoded with pyzbar -- a different library from the one that renders -- so a bug in
`qrcode` cannot hide by being on both sides.

Carried over from phase 1. The only change: `download_url` was removed with the
laptop-served links, so the payloads here are Drive links instead.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image
from pyzbar.pyzbar import decode

from app.qr import make_qr_png


def decode_png(png: bytes) -> list[str]:
    return [d.data.decode("utf-8") for d in decode(Image.open(io.BytesIO(png)))]


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view?usp=drivesdk",
        "https://drive.google.com/file/d/short/view",
        # Longer than any real Drive link, to leave headroom.
        "https://drive.google.com/file/d/" + "A" * 60 + "/view?usp=drivesdk&extra=" + "b" * 40,
    ],
)
def test_qr_round_trips_exactly(url: str) -> None:
    assert decode_png(make_qr_png(url)) == [url]


def test_a_drive_link_still_makes_a_compact_code() -> None:
    """A Drive link is ~80 characters. The code must stay small enough to print at a
    couple of centimetres and still scan: version 6 or below at this error level."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    url = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view?usp=drivesdk"
    q = qrcode.QRCode(error_correction=ERROR_CORRECT_M)
    q.add_data(url)
    q.make(fit=True)
    assert q.version <= 6


def test_quiet_zone_is_present() -> None:
    """A QR without its 4-module quiet zone often fails to scan. Not theoretical: the
    ZATCA invoice that started this project ships without one."""
    img = Image.open(io.BytesIO(make_qr_png("https://drive.google.com/file/d/x/view"))).convert("L")
    w, h = img.size
    for x in range(w):
        for y in list(range(40)) + list(range(h - 40, h)):
            assert img.getpixel((x, y)) == 255


def test_border_parameter_is_wired_through() -> None:
    url = "https://drive.google.com/file/d/x/view"
    with_border = Image.open(io.BytesIO(make_qr_png(url)))
    without = Image.open(io.BytesIO(make_qr_png(url, border=0)))
    assert with_border.size[0] > without.size[0]
