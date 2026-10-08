"""Data portability exporter implementing GDPR Article 20 requirements."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time

from myrm_agent_harness.core.security.data_erasure_portability.types import (
    DataPortabilityBundle,
)

logger = logging.getLogger(__name__)

_DEFAULT_SIGNING_KEY: bytes = b"myrm-portability-authority-v1"


class DataPortabilityExporter:
    """Exporter packaging user conversational, memory, and config assets into portable containers."""

    def __init__(self, signing_secret: bytes | None = None) -> None:
        self._signing_secret: bytes = signing_secret or _DEFAULT_SIGNING_KEY

    def export_bundle(
        self,
        tenant_id: str,
        conversations: list[dict[str, str]],
        memory_entries: list[dict[str, str]],
        agent_configs: list[dict[str, str]],
    ) -> DataPortabilityBundle:
        """Create a complete tamper-evident data portability bundle."""
        now = time.time()
        bundle_id = f"export-{secrets.token_hex(12)}"

        payload_repr = json.dumps(
            {
                "bundle_id": bundle_id,
                "tenant_id": tenant_id,
                "conversations": conversations,
                "memory_entries": memory_entries,
                "agent_configs": agent_configs,
                "exported_at": int(now),
            },
            sort_keys=True,
        )

        bundle_sha256 = hashlib.sha256(payload_repr.encode("utf-8")).hexdigest()
        bundle_signature = hmac.new(
            self._signing_secret,
            bundle_sha256.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return DataPortabilityBundle(
            bundle_id=bundle_id,
            tenant_id=tenant_id,
            exported_at=now,
            conversations=conversations,
            memory_entries=memory_entries,
            agent_configs=agent_configs,
            bundle_sha256=bundle_sha256,
            bundle_signature=bundle_signature,
        )

    def verify_bundle_integrity(self, bundle: DataPortabilityBundle) -> bool:
        """Verify the integrity and HMAC signature of a data portability bundle."""
        payload_repr = json.dumps(
            {
                "bundle_id": bundle.bundle_id,
                "tenant_id": bundle.tenant_id,
                "conversations": bundle.conversations,
                "memory_entries": bundle.memory_entries,
                "agent_configs": bundle.agent_configs,
                "exported_at": int(bundle.exported_at),
            },
            sort_keys=True,
        )

        recomputed_sha256 = hashlib.sha256(payload_repr.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(bundle.bundle_sha256, recomputed_sha256):
            logger.warning("Bundle '%s' SHA-256 hash mismatch.", bundle.bundle_id)
            return False

        expected_sig = hmac.new(
            self._signing_secret,
            recomputed_sha256.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(bundle.bundle_signature, expected_sig)
