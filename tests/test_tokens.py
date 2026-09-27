"""Token properties. The token IS the access control, so its entropy is load-bearing."""

from __future__ import annotations

import re
import string

from app.db import new_token

URLSAFE = set(string.ascii_letters + string.digits + "-_")


def test_token_is_url_safe() -> None:
    for _ in range(1000):
        assert set(new_token()) <= URLSAFE


def test_token_length_matches_128_bits() -> None:
    # secrets.token_urlsafe(16) -> 16 bytes -> 22 base64url chars, no padding.
    token = new_token()
    assert len(token) == 22
    assert "=" not in token


def test_tokens_are_unique_at_scale() -> None:
    """100k draws with zero collisions.

    This does not prove 128-bit entropy, but it would catch the classic regressions:
    a seeded PRNG, a truncated token, or a counter dressed up as a token.
    """
    tokens = {new_token() for _ in range(100_000)}
    assert len(tokens) == 100_000


def test_tokens_are_not_sequential() -> None:
    """Consecutive tokens must share no common prefix beyond chance."""
    a, b = new_token(), new_token()
    common = 0
    for x, y in zip(a, b):
        if x != y:
            break
        common += 1
    assert common < 6, f"tokens look sequential: {a} / {b}"


def test_token_fits_a_short_url() -> None:
    url = f"https://qr.example.com/d/{new_token()}"
    assert len(url) < 60, "keep the QR payload small enough to print at ~2cm"
    assert re.fullmatch(r"https://[\w.\-]+/d/[\w\-]{22}", url)
