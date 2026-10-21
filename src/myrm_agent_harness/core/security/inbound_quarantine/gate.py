"""Composite Inbound Zero-Trust Quarantine Gate.

[INPUT]
- Inbound channel messages, senders, recipients, and human release requests.

[OUTPUT]
- Redacted safe content for LLM ingestion, or decrypted payloads for human release cards.

[POS]
- Unified boundary orchestrating sniffer detection and ephemeral vault isolation.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.inbound_quarantine.sniffer import (
    InboundZeroTrustSniffer,
)
from myrm_agent_harness.core.security.inbound_quarantine.types import (
    QuarantineDetectionResult,
    QuarantineRecord,
    ReleasedSecretInfo,
)
from myrm_agent_harness.core.security.inbound_quarantine.vault import (
    InboundQuarantineVault,
)


class InboundQuarantineGate:
    """Zero-trust interception gate filtering raw credentials before LLM context construction."""

    def __init__(
        self,
        vault: InboundQuarantineVault | None = None,
        base_release_url: str = "/api/v1/security/inbound-quarantine/records",
    ) -> None:
        """Initialize gate with quarantine vault."""
        self._vault = vault or InboundQuarantineVault()
        self._base_release_url = base_release_url.rstrip("/")

    def inspect_and_quarantine(
        self,
        content: str,
        channel_type: str = "email",
        sender: str = "",
        recipient: str = "",
        ttl_seconds: float = 900.0,
    ) -> QuarantineDetectionResult:
        """Inspect inbound message and enforce physical quarantine if secrets are detected."""
        risks = InboundZeroTrustSniffer.sniff(content)
        if not risks:
            return QuarantineDetectionResult(
                is_quarantined=False,
                detected_risks=[],
                safe_content=content,
            )

        # Sensitive credentials detected -> Physical quarantine required
        record = self._vault.store(
            channel_type=channel_type,
            sender=sender,
            recipient=recipient,
            original_content=content,
            risks=risks,
            ttl_seconds=ttl_seconds,
        )

        safe_placeholder = InboundZeroTrustSniffer.redact_to_placeholder(
            text=content,
            quarantine_id=record.quarantine_id,
            risks=risks,
        )
        release_card_url = f"{self._base_release_url}/{record.quarantine_id}/release"

        return QuarantineDetectionResult(
            is_quarantined=True,
            detected_risks=risks,
            safe_content=safe_placeholder,
            quarantine_id=record.quarantine_id,
            release_card_url=release_card_url,
            expires_at=record.expires_at,
        )

    def release_quarantine(
        self,
        quarantine_id: str,
    ) -> ReleasedSecretInfo | None:
        """Authorize release and decryption of quarantined content for human viewing."""
        return self._vault.release_payload(quarantine_id)

    def get_quarantine_record(
        self,
        quarantine_id: str,
    ) -> QuarantineRecord | None:
        """Retrieve non-sensitive quarantine metadata."""
        return self._vault.get_record(quarantine_id)

    def purge_expired(self) -> int:
        """Destroy expired quarantine entries."""
        return self._vault.purge_expired()
