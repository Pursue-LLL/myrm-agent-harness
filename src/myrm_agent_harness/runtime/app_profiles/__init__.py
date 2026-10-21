"""Per-App Operating Profiles and Ephemeral Observation Self-Healing Suite.

Standardized per-app quirk management, code-over-prompt enforcement,
multi-app universal rule promotion, and falsification-first adaptive correction.

[INPUT]
- app_profile_registry
- observation_refinement_engine
- profile_types

[OUTPUT]
- (模块级副作用与注册)

[POS]
Per-App Operating Profiles and Ephemeral Observation Self-Healing Suite.
"""

from .app_profile_registry import AppProfileRegistry
from .observation_refinement_engine import (
    EphemeralInfoDetector,
    ObservationRefinementEngine,
)
from .profile_types import (
    AppObservation,
    AppOperatingProfile,
    FalsificationEvidence,
    FalsificationStatus,
    ObservationTier,
    PromotionEvaluationResult,
)

__all__ = [
    "AppObservation",
    "AppOperatingProfile",
    "AppProfileRegistry",
    "EphemeralInfoDetector",
    "FalsificationEvidence",
    "FalsificationStatus",
    "ObservationRefinementEngine",
    "ObservationTier",
    "PromotionEvaluationResult",
]
