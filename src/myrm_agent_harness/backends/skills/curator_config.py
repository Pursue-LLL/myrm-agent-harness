"""Skill curator configuration, validated at construction.

A curator sweep runs unattended and without confirmation, so a degenerate
threshold (a zero-day stale window, an active-skill limit of zero) would make
every eligible skill (not pinned, past its grace period) due in a single pass. The
config type therefore refuses to exist with such values and raises ``ValueError``
instead.

[INPUT]
- dataclasses::asdict, dataclass (POS: Python dataclass utilities)

[OUTPUT]
- CuratorConfig: Validated configuration for the skill curator / forgetting strategy.

[POS]
Skill curator configuration. The single place that defines the curator knobs, their
defaults and the ranges in which a sweep stays safe to run unattended.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

_DEFAULT_STALE_DAYS = 30
_DEFAULT_ARCHIVE_DAYS = 90
_DEFAULT_MIN_SUCCESS_RATE = 0.3
_DEFAULT_MAX_SKILLS = 50
_DEFAULT_MIN_CALL_COUNT_FOR_QUALITY_CHECK = 5
_DEFAULT_GRACE_PERIOD_DAYS = 7
_DEFAULT_INTERVAL_HOURS = 168  # 7 days
_DEFAULT_CONSOLIDATION_MIN_SKILLS = 10
_DEFAULT_CONSOLIDATION_MIN_CLUSTER_SIZE = 3
_DEFAULT_CONSOLIDATION_SIMILARITY_THRESHOLD = 0.75

# Inclusive lower bounds. Below them a threshold collapses onto "now" (every skill is
# due) or removes the capacity (every skill is over the limit).
_MINIMUMS: dict[str, int] = {
    "interval_hours": 1,
    "stale_after_days": 1,
    "archive_after_days": 1,
    "grace_period_days": 0,
    "max_skills": 1,
    "min_call_count_for_quality_check": 1,
    "consolidation_min_skills": 1,
    "consolidation_min_cluster_size": 2,
}

# Fields that are probabilities / similarities and must stay within [0, 1].
_RATIOS: tuple[str, ...] = ("min_success_rate", "consolidation_similarity_threshold")


def _config_int(data: dict[str, object], key: str, default: int) -> int:
    value = data.get(key, default)
    if isinstance(value, int | float | str):
        return int(value)
    raise TypeError(f"CuratorConfig.{key} must be a number, got {type(value).__name__}")


def _config_float(data: dict[str, object], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, int | float | str):
        return float(value)
    raise TypeError(f"CuratorConfig.{key} must be a number, got {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class CuratorConfig:
    """Configuration for the skill curator / forgetting strategy.

    Provides all knobs required by the curator engine and the forgetting
    strategy.  Every field has a sensible default so the curator works
    out-of-the-box without user configuration.  Values outside the safe ranges
    raise ``ValueError`` on construction.
    """

    enabled: bool = True
    """Master switch.  Set to False to disable the curator entirely."""

    interval_hours: int = _DEFAULT_INTERVAL_HOURS
    """Minimum hours between curator runs (default 168 = 7 days)."""

    stale_after_days: int = _DEFAULT_STALE_DAYS
    """Days of inactivity before a skill is marked stale (default 30)."""

    archive_after_days: int = _DEFAULT_ARCHIVE_DAYS
    """Days of inactivity before a stale skill is archived (default 90)."""

    grace_period_days: int = _DEFAULT_GRACE_PERIOD_DAYS
    """Days after skill creation during which it is exempt from curator
    transitions (default 7).  Gives new skills time to accumulate usage."""

    min_success_rate: float = _DEFAULT_MIN_SUCCESS_RATE
    """Minimum success rate threshold (0.0-1.0).  Skills below this after
    min_call_count_for_quality_check observed outcomes may be considered low quality."""

    max_skills: int = _DEFAULT_MAX_SKILLS
    """Maximum number of active skills before LRU eviction kicks in."""

    min_call_count_for_quality_check: int = _DEFAULT_MIN_CALL_COUNT_FOR_QUALITY_CHECK
    """Minimum number of observed run outcomes before evaluating success rate."""

    protect_installed_skills: bool = True
    """When True, the skills the caller reports as installed (hub/registry) via
    ``SkillCurator.run(installed_names=...)`` are exempt from curator transitions."""

    protect_system_skills: bool = True
    """When True, prebuilt/system skills (storage path contains ``/prebuilt/``)
    are exempt from curator transitions."""

    # --- Consolidation (Umbrella Merge) settings ---

    consolidation_enabled: bool = False
    """Enable skill consolidation (umbrella merge) during curator runs."""

    consolidation_min_skills: int = _DEFAULT_CONSOLIDATION_MIN_SKILLS
    """Minimum active skills before consolidation analysis is triggered."""

    consolidation_min_cluster_size: int = _DEFAULT_CONSOLIDATION_MIN_CLUSTER_SIZE
    """Minimum skills in a cluster to be considered for consolidation."""

    consolidation_similarity_threshold: float = _DEFAULT_CONSOLIDATION_SIMILARITY_THRESHOLD
    """Minimum embedding cosine similarity to group skills into a cluster."""

    def __post_init__(self) -> None:
        for name, minimum in _MINIMUMS.items():
            value = getattr(self, name)
            if value < minimum:
                raise ValueError(f"CuratorConfig.{name} must be >= {minimum}, got {value}")
        for name in _RATIOS:
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"CuratorConfig.{name} must be between 0 and 1, got {value}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> CuratorConfig:
        if not data or not isinstance(data, dict):
            return cls()
        return cls(
            enabled=bool(data.get("enabled", True)),
            interval_hours=_config_int(data, "interval_hours", _DEFAULT_INTERVAL_HOURS),
            stale_after_days=_config_int(data, "stale_after_days", _DEFAULT_STALE_DAYS),
            archive_after_days=_config_int(data, "archive_after_days", _DEFAULT_ARCHIVE_DAYS),
            grace_period_days=_config_int(data, "grace_period_days", _DEFAULT_GRACE_PERIOD_DAYS),
            min_success_rate=_config_float(data, "min_success_rate", _DEFAULT_MIN_SUCCESS_RATE),
            max_skills=_config_int(data, "max_skills", _DEFAULT_MAX_SKILLS),
            min_call_count_for_quality_check=_config_int(
                data, "min_call_count_for_quality_check", _DEFAULT_MIN_CALL_COUNT_FOR_QUALITY_CHECK
            ),
            protect_installed_skills=bool(data.get("protect_installed_skills", True)),
            protect_system_skills=bool(data.get("protect_system_skills", True)),
            consolidation_enabled=bool(data.get("consolidation_enabled", False)),
            consolidation_min_skills=_config_int(data, "consolidation_min_skills", _DEFAULT_CONSOLIDATION_MIN_SKILLS),
            consolidation_min_cluster_size=_config_int(
                data, "consolidation_min_cluster_size", _DEFAULT_CONSOLIDATION_MIN_CLUSTER_SIZE
            ),
            consolidation_similarity_threshold=_config_float(
                data, "consolidation_similarity_threshold", _DEFAULT_CONSOLIDATION_SIMILARITY_THRESHOLD
            ),
        )
