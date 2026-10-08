"""Security Audit Explicit Coverage & Replayable Repair Bundle Package.

Exposes application model contract validation, explicit coverage disclosure,
adversarial independent challenge, and replayable repair bundles (gstack CSO model).
"""

from myrm_agent_harness.core.security.audit_coverage.engine import (
    AuditCoverageEngine,
)
from myrm_agent_harness.core.security.audit_coverage.independent_challenge import (
    IndependentChallengeReviewer,
)
from myrm_agent_harness.core.security.audit_coverage.model_contract import (
    ApplicationModelContract,
)
from myrm_agent_harness.core.security.audit_coverage.repair_bundle import (
    ReplayableRepairEngine,
)
from myrm_agent_harness.core.security.audit_coverage.types import (
    ApplicationModel,
    AuditCoverageError,
    AuditFinding,
    ChallengeVerdict,
    CoverageCategory,
    CoverageScopeItem,
    CoverageStatus,
    ExplicitAuditCoverageReport,
    FindingSeverity,
    RepairBundleVerificationError,
    RepairPatch,
    ReplayableRepairBundle,
    UnsupportedFindingError,
    VerificationTier,
)

__all__ = [
    "ApplicationModel",
    "ApplicationModelContract",
    "AuditCoverageEngine",
    "AuditCoverageError",
    "AuditFinding",
    "ChallengeVerdict",
    "CoverageCategory",
    "CoverageScopeItem",
    "CoverageStatus",
    "ExplicitAuditCoverageReport",
    "FindingSeverity",
    "IndependentChallengeReviewer",
    "RepairBundleVerificationError",
    "RepairPatch",
    "ReplayableRepairBundle",
    "ReplayableRepairEngine",
    "UnsupportedFindingError",
    "VerificationTier",
]
