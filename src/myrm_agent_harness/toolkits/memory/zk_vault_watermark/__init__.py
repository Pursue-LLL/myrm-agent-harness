"""Zero Knowledge Memory Vault and Anti-Cloning Watermarking Suite (Item 159).

[INPUT]
- Passphrases, memory records, sensitivity classifications, and sandbox environment tokens.

[OUTPUT]
- ZeroKnowledgeMemoryVaultManager, EnvelopeCryptoEngine, InvisibleWatermarkEngine,
  SensitivityDistillationExporter, SandboxAntiCloningGate, and core cryptographic models.

[POS]
- Module exports in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

from .anti_cloning_gate import SandboxAntiCloningGate
from .distillation_exporter import SensitivityDistillationExporter
from .envelope_crypto import EnvelopeCryptoEngine
from .models import (
    DistilledExportPackage,
    DistilledMemoryItem,
    EncryptedEnvelope,
    InstanceBindingFingerprint,
    MemorySensitivityTier,
    ProvenanceWatermark,
)
from .watermark_engine import InvisibleWatermarkEngine
from .zk_vault_manager import ZeroKnowledgeMemoryVaultManager

__all__ = [
    "DistilledExportPackage",
    "DistilledMemoryItem",
    "EncryptedEnvelope",
    "EnvelopeCryptoEngine",
    "InstanceBindingFingerprint",
    "InvisibleWatermarkEngine",
    "MemorySensitivityTier",
    "ProvenanceWatermark",
    "SandboxAntiCloningGate",
    "SensitivityDistillationExporter",
    "ZeroKnowledgeMemoryVaultManager",
]
