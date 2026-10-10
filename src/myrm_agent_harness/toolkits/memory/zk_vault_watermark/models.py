"""Data models for Zero Knowledge Memory Vault and Provenance Watermarking (Item 159).

[INPUT]
- Cryptographic keys, sensitivity classifications, watermark payloads, binding hardware tokens.

[OUTPUT]
- EncryptedEnvelope, ProvenanceWatermark, InstanceBindingFingerprint, and DistilledMemoryAsset.

[POS]
- Core models in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

MemorySensitivityTier = Literal[
    "public_sharable",
    "team_internal",
    "strictly_private_pii",
]


@dataclass(slots=True)
class EncryptedEnvelope:
    """Envelope-encrypted memory payload protected by a local master key (KEK/DEK)."""

    ciphertext_hex: str
    iv_hex: str
    salt_hex: str
    encrypted_dek_hex: str
    algorithm: str = "AES-256-GCM-Simulated"
    created_at: str = ""


@dataclass(slots=True)
class ProvenanceWatermark:
    """Invisible watermark metadata identifying origin tenant, operator, and export timestamp."""

    tenant_id: str
    user_id: str
    timestamp_iso: str
    signature: str = ""


@dataclass(slots=True)
class InstanceBindingFingerprint:
    """Hardware and sandbox environment binding token preventing unauthorized cloning."""

    instance_guid: str
    volume_id: str
    tenant_id: str
    bound_at: str = ""
    is_locked: bool = False


@dataclass(slots=True)
class DistilledMemoryItem:
    """A memory item tagged with sensitivity tier and distilled for safe external sharing."""

    memory_id: str
    content: str
    sensitivity_tier: MemorySensitivityTier
    category: str = "general"
    redacted: bool = False


@dataclass(slots=True)
class DistilledExportPackage:
    """Export container carrying distilled memories alongside embedded invisible provenance watermarks."""

    tenant_id: str
    target_tier: MemorySensitivityTier
    exported_at: str
    items: list[DistilledMemoryItem] = field(default_factory=list)
    watermarked_text: str = ""
    watermark_signature: str = ""
