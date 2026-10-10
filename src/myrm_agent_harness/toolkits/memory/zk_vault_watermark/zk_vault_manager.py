"""Master manager coordinating envelope encryption, provenance watermarking, and anti-cloning (Item 159).

[INPUT]
- Memory items, sensitivity tiers, local passphrases, export requests, and hardware environment tokens.

[OUTPUT]
- Encrypted envelopes, unsealed memory records, distilled watermarked export packages, and access decisions.

[POS]
- Vault master manager in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .anti_cloning_gate import SandboxAntiCloningGate
from .distillation_exporter import SensitivityDistillationExporter
from .envelope_crypto import EnvelopeCryptoEngine
from .models import (
    DistilledExportPackage,
    DistilledMemoryItem,
    EncryptedEnvelope,
    MemorySensitivityTier,
    ProvenanceWatermark,
)
from .watermark_engine import InvisibleWatermarkEngine


class ZeroKnowledgeMemoryVaultManager:
    """Master controller orchestrating envelope encryption, sensitivity distillation, and invisible watermarks."""

    def __init__(
        self,
        crypto: EnvelopeCryptoEngine | None = None,
        watermarker: InvisibleWatermarkEngine | None = None,
        distiller: SensitivityDistillationExporter | None = None,
        cloning_gate: SandboxAntiCloningGate | None = None,
    ) -> None:
        self.crypto = crypto or EnvelopeCryptoEngine()
        self.watermarker = watermarker or InvisibleWatermarkEngine()
        self.distiller = distiller or SensitivityDistillationExporter()
        self.cloning_gate = cloning_gate or SandboxAntiCloningGate()

        self._items: dict[str, DistilledMemoryItem] = {}
        self._envelopes: dict[str, EncryptedEnvelope] = {}

    def seal_and_store_memory(
        self,
        memory_id: str,
        content: str,
        sensitivity_tier: MemorySensitivityTier = "team_internal",
        category: str = "general",
        passphrase: str = "",
    ) -> EncryptedEnvelope:
        """Encrypt memory payload with transient DEK sealed by local master passphrase."""
        payload_dict = {
            "memory_id": memory_id,
            "content": content,
            "sensitivity_tier": sensitivity_tier,
            "category": category,
        }
        serialized = json.dumps(payload_dict, ensure_ascii=False)
        envelope = self.crypto.encrypt_payload(serialized, passphrase=passphrase)

        self._envelopes[memory_id] = envelope
        self._items[memory_id] = DistilledMemoryItem(
            memory_id=memory_id,
            content=content,
            sensitivity_tier=sensitivity_tier,
            category=category,
            redacted=False,
        )
        return envelope

    def unseal_memory(
        self,
        memory_id: str,
        passphrase: str,
    ) -> DistilledMemoryItem:
        """Decrypt envelope using master passphrase and return memory record."""
        envelope = self._envelopes.get(memory_id)
        if envelope is None:
            raise KeyError(f"Encrypted envelope for memory {memory_id} not found")

        plaintext_json = self.crypto.decrypt_payload(envelope, passphrase=passphrase)
        data = json.loads(plaintext_json)

        item = DistilledMemoryItem(
            memory_id=data["memory_id"],
            content=data["content"],
            sensitivity_tier=data["sensitivity_tier"],
            category=data["category"],
            redacted=False,
        )
        self._items[memory_id] = item
        return item

    def get_memory(self, memory_id: str) -> DistilledMemoryItem | None:
        """Retrieve memory record from active decrypted cache."""
        return self._items.get(memory_id)

    def list_memories(
        self,
        tier: MemorySensitivityTier | None = None,
    ) -> list[DistilledMemoryItem]:
        """List active memory items, optionally filtered by sensitivity tier."""
        items = list(self._items.values())
        if tier is not None:
            return [it for it in items if it.sensitivity_tier == tier]
        return items

    def export_distilled_package(
        self,
        tenant_id: str,
        user_id: str,
        target_tier: MemorySensitivityTier = "public_sharable",
        redact_pii: bool = True,
        timestamp_iso: str | None = None,
    ) -> DistilledExportPackage:
        """Export sanitized memories with invisible zero-width provenance watermark."""
        now_str = timestamp_iso or datetime.now(timezone.utc).isoformat()
        all_items = list(self._items.values())

        # 1. Distill and sanitize memories according to target tier
        distilled_items = self.distiller.distill_memories(
            all_items,
            target_tier=target_tier,
            redact_pii=redact_pii,
        )

        # 2. Render structured Markdown export text
        raw_markdown = self.distiller.render_markdown_document(
            distilled_items,
            target_tier=target_tier,
        )

        # 3. Inject invisible zero-width provenance watermark
        watermarked_text, watermark = self.watermarker.embed_watermark(
            text=raw_markdown,
            tenant_id=tenant_id,
            user_id=user_id,
            timestamp_iso=now_str,
        )

        return DistilledExportPackage(
            tenant_id=tenant_id,
            target_tier=target_tier,
            exported_at=now_str,
            items=distilled_items,
            watermarked_text=watermarked_text,
            watermark_signature=watermark.signature,
        )

    def verify_exported_watermark(
        self,
        exported_text: str,
    ) -> ProvenanceWatermark | None:
        """Extract and verify invisible zero-width provenance watermark from leaked text."""
        return self.watermarker.extract_watermark(exported_text)

    def verify_sandbox_residency(
        self,
        instance_guid: str,
        volume_id: str,
        tenant_id: str,
    ) -> tuple[bool, str]:
        """Verify that current execution environment matches bound sandbox fingerprint."""
        return self.cloning_gate.verify_environment(
            current_instance_guid=instance_guid,
            current_volume_id=volume_id,
            current_tenant_id=tenant_id,
        )

    def unlock_sandbox_residency(
        self,
        provided_passphrase: str,
        expected_passphrase: str,
        new_instance_guid: str,
        new_volume_id: str,
        tenant_id: str,
    ) -> bool:
        """Unlock hardware binding and re-bind to new sandbox instance."""
        return self.cloning_gate.unlock_and_rebind(
            provided_passphrase=provided_passphrase,
            expected_passphrase=expected_passphrase,
            new_instance_guid=new_instance_guid,
            new_volume_id=new_volume_id,
            tenant_id=tenant_id,
        )
