"""Package exports for SecOps Audit and High-Risk Surface Gate.

[INPUT]
- None.

[OUTPUT]
- HighRiskSurfaceScanner, RuntimeSkillIntegrityVerifier
- Types, enums, exceptions, and data models.

[POS]
- Harness core security package for SecOps CI gating and Skill supply-chain integrity.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.secops_audit.skill_verifier import (
    RuntimeSkillIntegrityVerifier,
)
from myrm_agent_harness.core.security.secops_audit.surface_scanner import (
    HighRiskSurfaceScanner,
)
from myrm_agent_harness.core.security.secops_audit.types import (
    DiffSurfaceAnalysisResult,
    RiskCategory,
    SecOpsAuditError,
    SkillAuditReport,
    SkillIntegrityManifest,
    SkillPermission,
    SkillTamperingError,
    SurfaceLabel,
    SurfaceMatch,
    UnsignedSkillError,
)

__all__ = [
    "DiffSurfaceAnalysisResult",
    "HighRiskSurfaceScanner",
    "RiskCategory",
    "RuntimeSkillIntegrityVerifier",
    "SecOpsAuditError",
    "SkillAuditReport",
    "SkillIntegrityManifest",
    "SkillPermission",
    "SkillTamperingError",
    "SurfaceLabel",
    "SurfaceMatch",
    "UnsignedSkillError",
]
