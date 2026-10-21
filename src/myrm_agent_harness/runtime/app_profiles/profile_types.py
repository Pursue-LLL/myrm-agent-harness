"""Data models and type definitions for Per-App Operating Profiles and Self-Healing Observations.

Provides structured schemas for application-specific operational quirks, ephemeral
observation isolation, falsification-first refinement, and universal rule promotions.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ObservationTier
- FalsificationStatus
- AppObservation
- FalsificationEvidence
- PromotionEvaluationResult
- AppOperatingProfile

[POS]
Data models and type definitions for Per-App Operating Profiles and Self-Healing Observations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ObservationTier(StrEnum):
    """Tier defining where an operational observation belongs."""

    EPHEMERAL_LOCAL = "ephemeral_local"  # Temporary/perishable: absolute coordinates, window IDs, transient ports
    PER_APP_STABLE = "per_app_stable"  # Stable application quirk: e.g. headless render needs flag, chromium devtools port
    PROMOTED_UNIVERSAL = "promoted_universal"  # Universal prompt rule: proven across >= 2 different apps
    CONVERTED_TO_CODE = "converted_to_code"  # Lowered into tool engine implementation instead of prompt text


class FalsificationStatus(StrEnum):
    """Lifecycle status of an operating assumption or quirk."""

    ACTIVE = "active"  # Validated and active
    UNDER_SCRUTINY = "under_scrutiny"  # Disputed by recent run, pending re-test
    FALSIFIED = "falsified"  # Proven wrong by empirical observation, superseded/invalidated
    SUPERSEDED = "superseded"  # Replaced by a more specific or refined rule


@dataclass(frozen=True)
class AppObservation:
    """A single operational finding or lesson learned during automation."""

    observation_id: str
    app_id: str
    feature_key: str
    statement: str
    tier: ObservationTier
    status: FalsificationStatus = FalsificationStatus.ACTIVE
    is_ephemeral: bool = False
    can_convert_to_code: bool = False
    code_hook_target: str = ""
    supporting_apps: tuple[str, ...] = field(default_factory=tuple)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class FalsificationEvidence:
    """Empirical evidence contradicting an existing profile observation or quirk."""

    app_id: str
    feature_key: str
    observed_behavior: str
    contradiction_reason: str
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PromotionEvaluationResult:
    """Result of evaluating whether an observation qualifies for promotion or code lowering."""

    feature_key: str
    current_tier: ObservationTier
    target_tier: ObservationTier
    qualified_apps_count: int
    qualifying_apps: tuple[str, ...]
    is_promoted: bool
    rationale: str
    recommended_code_patch: str = ""


@dataclass
class AppOperatingProfile:
    """Per-App operating profile containing deterministic quirks and operational lessons."""

    app_id: str
    display_name: str
    bundle_id: str = ""
    executable_path: str = ""
    deterministic_features: dict[str, str] = field(default_factory=dict)
    observations: dict[str, AppObservation] = field(default_factory=dict)
    schema_version: int = 1
    updated_at: float = field(default_factory=time.time)

    def get_observation(self, feature_key: str) -> AppObservation | None:
        """Lookup an observation by its unique feature key."""
        return self.observations.get(feature_key)

    def is_feature_falsified(self, feature_key: str) -> bool:
        """Check if an observation has been proven false or superseded."""
        obs = self.observations.get(feature_key)
        if obs is None:
            return False
        return obs.status in (FalsificationStatus.FALSIFIED, FalsificationStatus.SUPERSEDED)
