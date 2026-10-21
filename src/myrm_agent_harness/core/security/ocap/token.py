"""HMAC-SHA256 signature generation and validation for CapabilityHandle.

[INPUT]
- .types::CapabilityHandle, ResourceScope, CapabilityAction

[OUTPUT]
- sign_capability_handle: Produce cryptographically authenticated signature
- verify_capability_signature: Constant-time validation of capability authenticity

[POS]
Provides cryptographic unforgeability for Object-Capability tokens.
Ensures child agents or prompt injections cannot fabricate or tamper with capability scopes.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.core.security.ocap.types import CapabilityHandle

# Handles are minted and verified inside one process and never serialized, so the signing key is
# random per process and never configured or persisted.
_OCAP_SECRET: bytes = secrets.token_bytes(32)


def compute_capability_digest(handle: CapabilityHandle) -> bytes:
    """Compute deterministic canonical digest of capability handle contents."""
    canonical_actions = ",".join(sorted(a.value for a in handle.actions))
    canonical_paths = ";".join(sorted(handle.scope.paths))
    parent_id = handle.parent_handle_id or ""

    raw_payload = (
        f"id={handle.handle_id}|"
        f"iss={handle.issuer_id}|"
        f"sub={handle.subject_id}|"
        f"act={canonical_actions}|"
        f"paths={canonical_paths}|"
        f"iat={handle.issued_at:.3f}|"
        f"exp={handle.expires_at:.3f}|"
        f"parent={parent_id}"
    )
    return raw_payload.encode("utf-8")


def sign_capability_handle(handle: CapabilityHandle, secret: bytes | None = None) -> str:
    """Compute HMAC-SHA256 signature for a capability handle."""
    key = secret or _OCAP_SECRET
    payload = compute_capability_digest(handle)
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def verify_capability_signature(handle: CapabilityHandle, secret: bytes | None = None) -> bool:
    """Validate capability handle signature using timing-safe comparison."""
    if not handle.signature:
        return False
    expected = sign_capability_handle(handle, secret)
    return hmac.compare_digest(handle.signature, expected)
