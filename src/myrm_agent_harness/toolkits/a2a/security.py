"""A2A protocol security and cryptographic utilities.

Provides pure functions for HMAC-SHA256 signature computation, verification,
and credential sanitization without external web framework dependencies.

[INPUT]
- secret, payload, timestamp

[OUTPUT]
- compute_hmac_signature: Computes HMAC-SHA256 hex digest
- verify_hmac_signature: Constant-time signature verification with replay guard
- sanitize_bearer_token: Extracts pure bearer token from Authorization header
- mask_secret: Masks secrets for safe logging and audit trails

[POS]
Harness-level security primitives for A2A webhooks and peer authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def compute_hmac_signature(
    secret: str,
    body: bytes | str,
    timestamp: float | int | str,
) -> str:
    """Compute HMAC-SHA256 signature for A2A webhook delivery.

    The message format is: `{timestamp}.{body}`.
    """
    ts_bytes = f"{timestamp}.".encode("utf-8")
    body_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
    message = ts_bytes + body_bytes
    key = secret.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def verify_hmac_signature(
    secret: str,
    body: bytes | str,
    timestamp: float | int | str,
    signature: str,
    *,
    tolerance_sec: float = 300.0,
    current_time: float | None = None,
) -> bool:
    """Verify an HMAC-SHA256 signature with replay tolerance guard.

    Returns True if the signature matches and timestamp is within tolerance window.
    """
    if not secret or not signature:
        return False

    try:
        ts_float = float(timestamp)
    except (ValueError, TypeError):
        return False

    now = current_time if current_time is not None else time.time()
    if tolerance_sec > 0 and abs(now - ts_float) > tolerance_sec:
        return False

    expected = compute_hmac_signature(secret, body, timestamp)
    return hmac.compare_digest(expected, signature)


def sanitize_bearer_token(auth_header: str | None) -> str | None:
    """Extract stripped token from Authorization header (e.g. 'Bearer <token>')."""
    if not auth_header:
        return None
    trimmed = auth_header.strip()
    if trimmed.lower().startswith("bearer "):
        return trimmed[7:].strip()
    return trimmed


def mask_secret(secret: str | None, visible_chars: int = 4) -> str:
    """Mask secret token for audit logging."""
    if not secret:
        return "<none>"
    if len(secret) <= visible_chars:
        return "***"
    return f"***{secret[-visible_chars:]}"
