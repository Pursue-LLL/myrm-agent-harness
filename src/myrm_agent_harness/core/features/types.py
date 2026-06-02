"""Feature Flags type definitions.

[INPUT]

[OUTPUT]
- FeatureStage: 5-level lifecycle enum
- ExperimentalInfo: metadata for experimental features
- FeatureSpec: feature specification dataclass

[POS]
Foundation layer. All types are frozen and immutable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, unique


@unique
class FeatureStage(Enum):
    """5-level feature lifecycle stage.

    UnderDevelopment → Experimental → Stable → Deprecated → Removed
    """

    UNDER_DEVELOPMENT = "under_development"
    EXPERIMENTAL = "experimental"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    REMOVED = "removed"

    @property
    def is_visible_to_users(self) -> bool:
        return self in (
            FeatureStage.EXPERIMENTAL,
            FeatureStage.STABLE,
            FeatureStage.DEPRECATED,
        )

    @property
    def is_active(self) -> bool:
        return self not in (FeatureStage.REMOVED,)


@dataclass(frozen=True, slots=True)
class ExperimentalInfo:
    """Metadata for experimental features, drives the frontend settings menu."""

    name: str
    """Display name shown in the experimental features menu."""

    description: str
    """Detailed description of what this feature does and potential instability."""

    announcement: str = ""
    """Optional announcement text for newly available experimental features."""


@dataclass(frozen=True, slots=True)
class DeprecationInfo:
    """Metadata for deprecated features."""

    migration_hint: str
    """Guidance on what to use instead."""

    removal_version: str = ""
    """Target version for removal (empty = no specific version planned)."""


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Immutable specification for a single feature flag.

    Registered in FeatureRegistry at startup. Each spec defines the feature's
    identity, lifecycle stage, default state, and dependency relationships.
    """

    id: str
    """Unique identifier, e.g. 'skill_optimization', 'deep_research'."""

    key: str
    """Configuration key used in config files and API."""

    stage: FeatureStage
    """Current lifecycle stage."""

    default_enabled: bool
    """Whether this feature is enabled by default."""

    description: str
    """Human-readable description of the feature."""

    experimental_info: ExperimentalInfo | None = None
    """Present only when stage == EXPERIMENTAL."""

    deprecation_info: DeprecationInfo | None = None
    """Present only when stage == DEPRECATED."""

    depends_on: frozenset[str] = frozenset()
    """Set of feature IDs that must also be enabled for this feature to work."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("FeatureSpec.id must not be empty")
        if not self.key:
            raise ValueError("FeatureSpec.key must not be empty")
        if self.stage == FeatureStage.EXPERIMENTAL and self.experimental_info is None:
            raise ValueError(f"Feature '{self.id}' is EXPERIMENTAL but missing experimental_info")
        if self.stage == FeatureStage.DEPRECATED and self.deprecation_info is None:
            raise ValueError(f"Feature '{self.id}' is DEPRECATED but missing deprecation_info")
        if self.id in self.depends_on:
            raise ValueError(f"Feature '{self.id}' cannot depend on itself")
