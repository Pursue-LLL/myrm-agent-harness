"""Encrypted ephemeral quarantine vault for intercepted credentials.

[INPUT]
- Unsanitized message contents, TTL duration, and quarantine retrieval requests.

[OUTPUT]
- AES-GCM encrypted physical storage, automatic TTL expiration, and authorized human release.

[POS]
- Physical isolation barrier ensuring raw secrets never enter persistent agent memory.
"""

from __future__ import annotations

import base64
import os
import time
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from myrm_agent_harness.core.security.inbound_quarantine.types import (
    InboundQuarantineRiskType,
    InboundQuarantineStatus,
    QuarantineRecord,
    ReleasedSecretInfo,
)


class InboundQuarantineVault:
    """Ephemeral encrypted in-memory quarantine vault enforcing 15-minute destruction."""

    def __init__(self, key: bytes | None = None) -> None:
        """Initialize vault with random 256-bit AES-GCM key."""
        self._key = key or AESGCM.generate_key(bit_length=256)
        self._aesgcm = AESGCM(self._key)
        self._records: dict[str, QuarantineRecord] = {}

    def store(
        self,
        channel_type: str,
        sender: str,
        recipient: str,
        original_content: str,
        risks: list[InboundQuarantineRiskType],
        ttl_seconds: float = 900.0,  # 15 minutes
    ) -> QuarantineRecord:
        """Encrypt and store intercepted content physically isolated in the vault."""
        quarantine_id = f"quar_{uuid.uuid4().hex[:16]}"
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(
            nonce=nonce,
            data=original_content.encode("utf-8"),
            associated_data=quarantine_id.encode("utf-8"),
        )

        now = time.time()
        record = QuarantineRecord(
            quarantine_id=quarantine_id,
            channel_type=channel_type,
            sender=sender,
            recipient=recipient,
            ciphertext_b64=base64.b64encode(ciphertext).decode("ascii"),
            nonce_b64=base64.b64encode(nonce).decode("ascii"),
            detected_risks=list(risks),
            status=InboundQuarantineStatus.ACTIVE,
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        self._records[quarantine_id] = record
        return record

    def get_record(self, quarantine_id: str) -> QuarantineRecord | None:
        """Fetch metadata for quarantine record, checking for expiration."""
        record = self._records.get(quarantine_id)
        if record is None:
            return None
        if time.time() > record.expires_at:
            record.status = InboundQuarantineStatus.EXPIRED
        return record

    def release_payload(self, quarantine_id: str) -> ReleasedSecretInfo | None:
        """Decrypt intercepted content for authenticated human inspection."""
        record = self._records.get(quarantine_id)
        if record is None:
            return None
        if record.status == InboundQuarantineStatus.EXPIRED or time.time() > record.expires_at:
            record.status = InboundQuarantineStatus.EXPIRED
            return None

        nonce = base64.b64decode(record.nonce_b64.encode("ascii"))

        ciphertext = base64.b64decode(record.ciphertext_b64.encode("ascii"))
        plaintext_bytes = self._aesgcm.decrypt(
            nonce=nonce,
            data=ciphertext,
            associated_data=quarantine_id.encode("utf-8"),
        )
        decrypted_text = plaintext_bytes.decode("utf-8")

        record.status = InboundQuarantineStatus.RELEASED
        return ReleasedSecretInfo(
            quarantine_id=quarantine_id,
            detected_risks=list(record.detected_risks),
            original_content=decrypted_text,
            released_at=time.time(),
        )

    def purge_expired(self) -> int:
        """Purge and destroy expired records older than their TTL."""
        now = time.time()
        expired_ids = [
            qid for qid, rec in self._records.items()
            if rec.status == InboundQuarantineStatus.EXPIRED or now > rec.expires_at
        ]
        for qid in expired_ids:
            del self._records[qid]
        return len(expired_ids)

    def clear(self) -> None:
        """Flush all records from the vault."""
        self._records.clear()
