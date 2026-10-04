"""QR code rendering.

The payload is the Google Drive link for the file (~80 characters), never the file
itself: a QR code holds at most 2,953 bytes of binary data, far smaller than any real
PDF.
"""

from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_M


def make_qr_png(data: str, *, box_size: int = 10, border: int = 4) -> bytes:
    """Render `data` as a PNG QR code.

    border=4 modules is the quiet zone the QR standard requires. Leaving it out is the
    most common reason a printed QR fails to scan: the ZATCA invoice that started
    this project ships with none, and OpenCV could not read it until one was added.
    """
    qr = qrcode.QRCode(
        version=None,  # smallest version that fits
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
