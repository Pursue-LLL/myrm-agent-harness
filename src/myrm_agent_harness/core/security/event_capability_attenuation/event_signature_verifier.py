"""
[POS] src/myrm_agent_harness/core/security/event_capability_attenuation/event_signature_verifier.py
[INPUT] hashlib, hmac, threading, typing, .types (EventPayloadDescriptor)
[OUTPUT] EventSignatureVerifier

Cryptographic HMAC-SHA256 verification of incoming MCP events and webhook payloads
to prevent spoofing, tampered triggers, and unauthenticated wakeups.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import hmac
import threading

from .types import EventPayloadDescriptor


class EventSignatureVerifier:
    """Validates cryptographic authenticity of external event triggers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets: dict[str, bytes] = {}

    def register_source_secret(self, source_name: str, secret_key: str | bytes) -> None:
        """Register shared secret for an external event publisher (e.g., GitHub, MCP Server)."""
        sec = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
        with self._lock:
            self._secrets[source_name] = sec

    def remove_source(self, source_name: str) -> None:
        """Remove source secret."""
        with self._lock:
            self._secrets.pop(source_name, None)

    def compute_signature(self, source_name: str, payload_bytes: bytes) -> str:
        """Compute expected HMAC-SHA256 hex digest for given payload."""
        with self._lock:
            secret = self._secrets.get(source_name)
        if secret is None:
            raise ValueError(f"No secret key registered for source '{source_name}'.")

        return hmac.new(secret, payload_bytes, hashlib.sha256).hexdigest()

    def verify_event(
        self,
        event_id: str,
        source_name: str,
        event_type: str,
        timestamp: float,
        raw_payload_bytes: bytes,
        signature: str | None,
    ) -> EventPayloadDescriptor:
        """Verify signature and return EventPayloadDescriptor with is_verified status."""
        with self._lock:
            secret = self._secrets.get(source_name)

        if secret is None or signature is None:
            return EventPayloadDescriptor(
                event_id=event_id,
                source_name=source_name,
                event_type=event_type,
                timestamp=timestamp,
                raw_payload_bytes=raw_payload_bytes,
                signature=signature,
                is_verified=False,
            )

        expected = hmac.new(secret, raw_payload_bytes, hashlib.sha256).hexdigest()
        is_valid = hmac.compare_digest(expected, signature)

        return EventPayloadDescriptor(
            event_id=event_id,
            source_name=source_name,
            event_type=event_type,
            timestamp=timestamp,
            raw_payload_bytes=raw_payload_bytes,
            signature=signature,
            is_verified=is_valid,
        )
