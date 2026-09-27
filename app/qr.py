"""QR code rendering.

The encoded payload is always a short absolute URL of the form
`https://host/d/<token>` (~35 chars), never the file itself and never a third-party
storage link. Short payload -> low module count -> the code stays legible when
printed small on a quotation and scans fast from a phone at an angle.
"""

from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def download_url(base_url: str, token: str) -> str:
    return f"{base_url.rstrip('/')}/d/{token}"


def make_qr_png(data: str, *, box_size: int = 10, border: int = 4) -> bytes:
    """Render `data` as a PNG QR code.

    border=4 modules is the spec-mandated quiet zone. Omitting it is the single most
    common reason a printed QR fails to scan -- the invoice we analysed at the start
    of this project shipped with no quiet zone, and OpenCV could not read it until
    one was added back.
    """
    qr = qrcode.QRCode(
        version=None,  # auto-size to the smallest version that fits
        error_correction=ERROR_CORRECT_M,  # ~15% recovery; survives print smudging
        box_size=box_size,
        border=border,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
