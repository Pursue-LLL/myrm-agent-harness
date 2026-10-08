"""Client-Side PII Auto-Sanitization and Local Vault Reverse Mapping module.

[INPUT]
None.

[OUTPUT]
- PiiEntityType, PiiEntityMatch, SanitizationResult, DesanitizationResult
- PiiVaultError, EntityDetectionError
- PiiEntityDetector
- LocalPiiMappingVault
- PiiTransformer

[POS]
Harness core security subsystem for client-side privacy preservation and reversible pseudonymization.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.pii_vault.detector import PiiEntityDetector
from myrm_agent_harness.core.security.pii_vault.transformer import PiiTransformer
from myrm_agent_harness.core.security.pii_vault.types import (
    DesanitizationResult,
    EntityDetectionError,
    PiiEntityMatch,
    PiiEntityType,
    PiiVaultError,
    SanitizationResult,
)
from myrm_agent_harness.core.security.pii_vault.vault import LocalPiiMappingVault

__all__ = [
    "PiiEntityType",
    "PiiEntityMatch",
    "SanitizationResult",
    "DesanitizationResult",
    "PiiVaultError",
    "EntityDetectionError",
    "PiiEntityDetector",
    "LocalPiiMappingVault",
    "PiiTransformer",
]
