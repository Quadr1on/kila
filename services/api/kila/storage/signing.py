"""HMAC-signed, short-lived object URLs for <img>/<iframe> previews."""

from __future__ import annotations

import hashlib
import hmac
import time

from kila.settings import get_settings


def _sig(object_id: str, exp: int) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"obj:{object_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def sign(object_id: str, ttl_s: int) -> tuple[str, int]:
    """Returns (relative url, expiry unix ts). The web app prefixes it with /api."""
    exp = int(time.time()) + ttl_s
    return f"/storage/signed/{object_id}?exp={exp}&sig={_sig(object_id, exp)}", exp


def check(object_id: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(_sig(object_id, exp), sig)
