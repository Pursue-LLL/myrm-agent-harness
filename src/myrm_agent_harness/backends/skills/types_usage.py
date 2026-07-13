"""Skill usage statistics and lifecycle tracking.

[INPUT]
- types_enums.SkillLifecycleStatus (POS: lifecycle state enum)

[OUTPUT]
- SkillUsageRecord: single skill invocation record for trend analysis
- SkillUsageStats: call/success/failure counts, lifecycle fields, usage history, serialization

[POS]
Usage stats persisted in {skill_dir}/.stats.json for curator / forgetting mechanism.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime

from myrm_agent_harness.backends.skills.types_enums import SkillLifecycleStatus

_MAX_HISTORY_ENTRIES = 200


@dataclass
class SkillUsageRecord:
    """Single skill invocation record for trend analysis."""

    timestamp: str
    success: bool
    duration_ms: float


@dataclass
class SkillUsageStats:
    """Skill usage statistics and lifecycle state.

    Tracks skill usage patterns for the curator / forgetting mechanism.
    Stored in {skill_dir}/.stats.json for lightweight persistence.

    The ``lifecycle_status`` and ``pinned`` fields extend pure usage
    tracking into lifecycle management — a natural evolution of the
    forgetting mechanism into a full curator system.
    """

    call_count: int = 0
    """Total number of times the skill was invoked"""

    success_count: int = 0
    """Number of successful invocations (no errors)"""

    failure_count: int = 0
    """Number of failed invocations"""

    last_used_at: datetime | None = None
    """Timestamp of last invocation"""

    total_duration_ms: float = 0.0
    """Cumulative duration in milliseconds"""

    # --- Lifecycle management (curator) ---

    lifecycle_status: str = SkillLifecycleStatus.ACTIVE
    """Current lifecycle state (active / stale / archived).
    Persisted in .stats.json and used by the curator engine."""

    pinned: bool = False
    """When True, the skill is exempt from all automated curator transitions
    (stale / archive) and from automated evolution.  User-initiated only."""

    merged_into: str | None = None
    """When archived via consolidation, the name of the umbrella skill this
    was merged into. None if not merged. Used for provenance tracking."""

    created_at: datetime | None = None
    """Timestamp when this stats record was first created.
    Used by the grace_period check to protect newly-discovered skills."""

    usage_history: list[SkillUsageRecord] = field(default_factory=list)
    """Rolling window of recent invocation records for trend analysis.
    Capped at _MAX_HISTORY_ENTRIES to bound disk usage."""

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage (0.0-1.0)"""
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count

    @property
    def avg_duration_ms(self) -> float:
        """Average duration per invocation"""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    @property
    def is_active(self) -> bool:
        return self.lifecycle_status == SkillLifecycleStatus.ACTIVE

    @property
    def is_stale(self) -> bool:
        return self.lifecycle_status == SkillLifecycleStatus.STALE

    @property
    def is_archived(self) -> bool:
        return self.lifecycle_status == SkillLifecycleStatus.ARCHIVED

    def to_dict(self) -> dict[str, object]:
        return {
            "call_count": self.call_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_used_at": (self.last_used_at.isoformat() if self.last_used_at else None),
            "total_duration_ms": self.total_duration_ms,
            "success_rate": self.success_rate,
            "avg_duration_ms": self.avg_duration_ms,
            "lifecycle_status": self.lifecycle_status,
            "pinned": self.pinned,
            "merged_into": self.merged_into,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "usage_history": [
                {"timestamp": r.timestamp, "success": r.success, "duration_ms": r.duration_ms}
                for r in self.usage_history
            ],
        }

    def append_usage(self, timestamp: str, success: bool, duration_ms: float) -> None:
        """Append a usage record and trim to rolling window."""
        self.usage_history.append(SkillUsageRecord(timestamp=timestamp, success=success, duration_ms=duration_ms))
        if len(self.usage_history) > _MAX_HISTORY_ENTRIES:
            self.usage_history = self.usage_history[-_MAX_HISTORY_ENTRIES:]

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> SkillUsageStats:
        if not data or not isinstance(data, dict):
            return cls()

        last_used_str = data.get("last_used_at")
        last_used_at = None
        if last_used_str and isinstance(last_used_str, str):
            with contextlib.suppress(ValueError):
                last_used_at = datetime.fromisoformat(last_used_str)

        created_at_str = data.get("created_at")
        created_at = None
        if created_at_str and isinstance(created_at_str, str):
            with contextlib.suppress(ValueError):
                created_at = datetime.fromisoformat(created_at_str)

        raw_status = data.get("lifecycle_status", SkillLifecycleStatus.ACTIVE)
        lifecycle_status = (
            raw_status
            if isinstance(raw_status, str) and raw_status in SkillLifecycleStatus.__members__.values()
            else SkillLifecycleStatus.ACTIVE
        )

        def _safe_int(val: object, default: int = 0) -> int:
            try:
                return int(val) if val is not None else default
            except (ValueError, TypeError):
                return default

        def _safe_float(val: object, default: float = 0.0) -> float:
            try:
                import math

                result = float(val) if val is not None else default
                return default if math.isnan(result) or math.isinf(result) else result
            except (ValueError, TypeError):
                return default

        history: list[SkillUsageRecord] = []
        raw_history = data.get("usage_history")
        if isinstance(raw_history, list):
            for entry in raw_history[-_MAX_HISTORY_ENTRIES:]:
                if isinstance(entry, dict):
                    with contextlib.suppress(KeyError, TypeError, ValueError):
                        history.append(
                            SkillUsageRecord(
                                timestamp=str(entry["timestamp"]),
                                success=bool(entry["success"]),
                                duration_ms=_safe_float(entry.get("duration_ms", 0.0)),
                            )
                        )

        return cls(
            call_count=_safe_int(data.get("call_count", 0)),
            success_count=_safe_int(data.get("success_count", 0)),
            failure_count=_safe_int(data.get("failure_count", 0)),
            last_used_at=last_used_at,
            total_duration_ms=_safe_float(data.get("total_duration_ms", 0.0)),
            lifecycle_status=lifecycle_status,
            pinned=bool(data.get("pinned", False)),
            merged_into=str(data["merged_into"]) if data.get("merged_into") else None,
            created_at=created_at,
            usage_history=history,
        )
