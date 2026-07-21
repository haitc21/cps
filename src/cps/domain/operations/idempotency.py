"""Idempotency fingerprint helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class InvalidFingerprintPayloadError(ValueError):
    """Raised when request payload cannot be canonicalized for fingerprinting."""


def canonical_fingerprint(payload: dict[str, Any]) -> str:
    """Return SHA-256 hex of canonical JSON with sorted keys and stable separators."""
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        msg = "request payload is not fingerprintable"
        raise InvalidFingerprintPayloadError(msg) from None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
