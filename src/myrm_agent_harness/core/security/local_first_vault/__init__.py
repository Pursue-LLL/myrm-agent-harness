"""Local-First Zero-Leak Vault and Zero-Knowledge E2EE Sharing Gateway Module.

Provides physical local disk persistence invariants, transparent in-situ DLP sanitization
for sensitive IPs, credentials, and commercial pricing, and AES-256-GCM zero-knowledge sharing.
"""

from __future__ import annotations

from .dlp_pipeline import TransparentDlpRedactionPipeline
from .e2ee_gateway import ZeroKnowledgeE2eeGateway
from .types import (
    DlpRedactionMatch,
    DlpRedactionResult,
    DlpSensitivityCategory,
    E2eeShareEnvelope,
    LocalVaultItem,
    VaultStorageMode,
)

__all__ = [
    "DlpRedactionMatch",
    "DlpRedactionResult",
    "DlpSensitivityCategory",
    "E2eeShareEnvelope",
    "LocalVaultItem",
    "TransparentDlpRedactionPipeline",
    "VaultStorageMode",
    "ZeroKnowledgeE2eeGateway",
]
