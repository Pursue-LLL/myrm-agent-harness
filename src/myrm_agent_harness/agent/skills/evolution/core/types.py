"""Data types for skill evolution system.

Simplified but complete implementation for skill self-evolution capability.
Focus on real-world utility with 54% less code than OpenSpace while maintaining full functionality.

[INPUT]
- (none)

[OUTPUT]
- EvolutionType: Type of skill evolution action.
- SkillMetrics: Quality metrics for skill tracking with 6-indicator system.
- SkillLineage: Simplified lineage tracking.
- SkillRecord: Complete skill record with evolution metadata.
- EvolutionRequest: Request for skill evolution (for concurrent processing). Supports GUI-First force_retry.
- SkillEvidenceGroup: Aggregated execution evidence for evidence-driven evolution.

[POS]
Data types for skill evolution system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class EvolutionType(StrEnum):
    """Type of skill evolution action."""

    FIX = "fix"  # Auto-repair failed/outdated skills
    DERIVED = "derived"  # Optimize/enhance based on user feedback
    CAPTURED = "captured"  # Capture repeated user commands as new skills
    SLICE_EXTRACTION = "slice_extraction"  # Extract from execution trace slice
    OPTIMIZE_DESCRIPTION = "optimize_description"  # Refine description for better matching


@dataclass
class EnvironmentFingerprint:
    """Environment context for a skill to ensure safe cross-device sharing."""

    os_platform: str = ""  # e.g., "Darwin", "Linux", "Windows"
    os_release: str = ""  # e.g., "21.6.0"
    python_version: str = ""  # e.g., "3.10.12"
    key_dependencies_hash: str = ""  # Hash of core dependencies (optional)
    custom_tags: dict[str, str] = field(default_factory=dict)  # Extensible tags

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_platform": self.os_platform,
            "os_release": self.os_release,
            "python_version": self.python_version,
            "key_dependencies_hash": self.key_dependencies_hash,
            "custom_tags": self.custom_tags,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnvironmentFingerprint:
        return cls(
            os_platform=data.get("os_platform", ""),
            os_release=data.get("os_release", ""),
            python_version=data.get("python_version", ""),
            key_dependencies_hash=data.get("key_dependencies_hash", ""),
            custom_tags=data.get("custom_tags", {}),
        )


@dataclass
class SkillMetrics:
    """Quality metrics for skill tracking with 6-indicator system.

    4 base counters:
    - total_selections: How many times skill was selected (including fallbacks)
    - applied_count: How many times skill actually started execution
    - completed_count: How many times execution completed (success + failure)
    - success_count: How many times execution succeeded

    4 derived rates (calculated on-the-fly):
    - fallback_rate: (total_selections - applied_count) / total_selections
    - applied_rate: applied_count / total_selections
    - completion_rate: completed_count / applied_count
    - effective_rate: success_count / applied_count (same as success_rate)

    Compatible with 2-indicator system via properties.
    """

    # Base counters
    total_selections: int = 0  # Selected (applied + fallback)
    applied_count: int = 0  # Actually started execution
    completed_count: int = 0  # Finished execution (success + failure)
    success_count: int = 0  # Finished successfully

    # Legacy fields for backwards compatibility
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int = 0  # For quick FIX triggering

    # User dissatisfaction signal (incremented on force_retry / manual correction)
    user_correction_count: int = 0

    # Derived rates (properties)
    @property
    def fallback_rate(self) -> float:
        """Rate of selections that were not applied (selected but fallback)."""
        if self.total_selections == 0:
            return 0.0
        return (self.total_selections - self.applied_count) / self.total_selections

    @property
    def applied_rate(self) -> float:
        """Rate of selections that were applied (actually executed)."""
        if self.total_selections == 0:
            return 0.0
        return self.applied_count / self.total_selections

    @property
    def completion_rate(self) -> float:
        """Rate of applied executions that completed (success + failure)."""
        if self.applied_count == 0:
            return 0.0
        return self.completed_count / self.applied_count

    @property
    def effective_rate(self) -> float:
        """Rate of applied executions that succeeded (same as success_rate)."""
        if self.applied_count == 0:
            return 0.0
        return self.success_count / self.applied_count

    # Backwards compatibility properties
    @property
    def success_rate(self) -> float:
        """Legacy: same as effective_rate."""
        return self.effective_rate

    @property
    def usage_count(self) -> int:
        """Legacy: same as applied_count."""
        return self.applied_count

    # Recording methods
    def record_applied(self, success: bool) -> None:
        """Record skill execution (applied and completed).

        Args:
            success: Whether execution succeeded
        """
        self.total_selections += 1  # Increment selections
        self.applied_count += 1  # Increment applied
        self.completed_count += 1  # Increment completed

        if success:
            self.success_count += 1
            self.consecutive_failures = 0
            self.last_success_at = datetime.now()
        else:
            self.consecutive_failures += 1
            self.last_failure_at = datetime.now()

    def record_fallback(self) -> None:
        """Record skill selection that was not applied (fallback).

        Use when skill is selected but execution is skipped (e.g., user cancelled).
        """
        self.total_selections += 1  # Increment selections only

    # Backwards compatibility methods (deprecated)
    def record_success(self) -> None:
        """Deprecated: use record_applied(success=True) instead."""
        self.record_applied(success=True)

    def record_failure(self) -> None:
        """Deprecated: use record_applied(success=False) instead."""
        self.record_applied(success=False)

    def should_trigger_fix(self, threshold: float = 0.5) -> bool:
        """Check if FIX evolution should be triggered.

        Triggers when:
        1. effective_rate < threshold AND applied_count >= 3, OR
        2. consecutive_failures >= 3 (immediate fix needed)
        """
        if self.consecutive_failures >= 3:
            return True
        return self.effective_rate < threshold and self.applied_count >= 3


@dataclass
class SkillLineage:
    """Simplified lineage tracking.

    Replaces complex DAG with simple versioning:
    - version: Simple integer version (v1, v2, v3...)
    - parent_id: Single parent skill_id (for FIX/DERIVED)
    - Reduces 5 tables to 1 simple field (95% complexity reduction)
    """

    evolution_type: EvolutionType
    version: int = 1
    parent_id: str | None = None  # None for CAPTURED, skill_id for FIX/DERIVED
    change_summary: str = ""  # LLM-generated description
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = ""  # Model name or "human"

    def to_dict(self) -> dict[str, Any]:
        return {
            "evolution_type": self.evolution_type.value,
            "version": self.version,
            "parent_id": self.parent_id,
            "change_summary": self.change_summary,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillLineage:
        return cls(
            evolution_type=EvolutionType(data["evolution_type"]),
            version=data.get("version", 1),
            parent_id=data.get("parent_id"),
            change_summary=data.get("change_summary", ""),
            created_at=(datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now()),
            created_by=data.get("created_by", ""),
        )


@dataclass
class SkillRecord:
    """Complete skill record with evolution metadata."""

    skill_id: str
    name: str
    description: str
    content: str
    path: str

    lineage: SkillLineage
    metrics: SkillMetrics = field(default_factory=SkillMetrics)
    environment: EnvironmentFingerprint | None = None

    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    is_active: bool = True
    evolution_locked: bool = False

    traps: list[dict[str, Any]] = field(default_factory=list)
    verification_steps: list[dict[str, Any]] = field(default_factory=list)

    def add_trap(self, trap: dict[str, Any]) -> bool:
        """Add trap with deduplication by description. Returns True if added."""
        desc = trap.get("description", "")
        if any(t.get("description") == desc for t in self.traps):
            for t in self.traps:
                if t.get("description") == desc:
                    t["occurrence_count"] = t.get("occurrence_count", 0) + 1
            return False
        trap.setdefault("occurrence_count", 1)
        trap.setdefault("severity", "medium")
        self.traps.append(trap)
        return True

    def get_high_severity_traps(self, max_count: int = 5) -> list[dict[str, Any]]:
        """Get top traps by severity for injection into skill prompt."""
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_traps = sorted(
            self.traps,
            key=lambda t: (
                severity_order.get(t.get("severity", "low"), 4),
                -t.get("occurrence_count", 0),
            ),
        )
        return sorted_traps[:max_count]

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "path": self.path,
            "lineage": self.lineage.to_dict(),
            "environment": self.environment.to_dict() if self.environment else None,
            "metrics": {
                "total_selections": self.metrics.total_selections,
                "applied_count": self.metrics.applied_count,
                "completed_count": self.metrics.completed_count,
                "success_count": self.metrics.success_count,
                "last_success_at": (self.metrics.last_success_at.isoformat() if self.metrics.last_success_at else None),
                "last_failure_at": (self.metrics.last_failure_at.isoformat() if self.metrics.last_failure_at else None),
                "consecutive_failures": self.metrics.consecutive_failures,
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "evolution_locked": self.evolution_locked,
            "traps": self.traps,
            "verification_steps": self.verification_steps,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillRecord:
        metrics_data = data.get("metrics", {})
        metrics = SkillMetrics(
            total_selections=metrics_data.get("total_selections", 0),
            applied_count=metrics_data.get("applied_count", 0),
            completed_count=metrics_data.get("completed_count", 0),
            success_count=metrics_data.get("success_count", 0),
            last_success_at=(
                datetime.fromisoformat(metrics_data["last_success_at"]) if metrics_data.get("last_success_at") else None
            ),
            last_failure_at=(
                datetime.fromisoformat(metrics_data["last_failure_at"]) if metrics_data.get("last_failure_at") else None
            ),
            consecutive_failures=metrics_data.get("consecutive_failures", 0),
        )

        return cls(
            skill_id=data["skill_id"],
            name=data["name"],
            description=data["description"],
            content=data["content"],
            path=data["path"],
            lineage=SkillLineage.from_dict(data["lineage"]),
            metrics=metrics,
            environment=(EnvironmentFingerprint.from_dict(data["environment"]) if data.get("environment") else None),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            is_active=data.get("is_active", True),
            evolution_locked=data.get("evolution_locked", False),
            traps=data.get("traps", []),
            verification_steps=data.get("verification_steps", []),
        )


@dataclass
class EvolutionRequest:
    """Request for skill evolution (for concurrent processing)."""

    evolution_type: EvolutionType
    skill_id: str | None = None  # For FIX/DERIVED, None for CAPTURED
    reason: str = ""  # Error message for FIX, user feedback for DERIVED, pattern for CAPTURED
    user_feedback: str = ""  # Optional user feedback for DERIVED
    repeated_commands: list[str] = field(default_factory=list)  # For CAPTURED
    session_id: str = ""  # For SLICE_EXTRACTION
    tool_call_ids: list[str] = field(default_factory=list)  # For SLICE_EXTRACTION
    agent_id: str | None = None  # For SLICE_EXTRACTION
    force_retry: bool = False  # GUI-First explicit flag to bypass cooldowns

    def to_dict(self) -> dict[str, Any]:
        return {
            "evolution_type": self.evolution_type.value,
            "skill_id": self.skill_id,
            "reason": self.reason,
            "user_feedback": self.user_feedback,
            "repeated_commands": self.repeated_commands,
            "session_id": self.session_id,
            "tool_call_ids": self.tool_call_ids,
            "agent_id": self.agent_id,
            "force_retry": self.force_retry,
        }


@dataclass
class EvolutionProposal:
    """Standardized evolution proposal data structure.

    Replaces direct file system modification. A proposal contains variants,
    sandbox test scores, and the suggested unified diff for human/GUI review.
    """

    skill_id: str
    evolution_type: EvolutionType
    original_content: str
    proposed_content: str
    diff: str
    score: float
    reasoning: str
    task_context: str = ""
    trajectory: str = ""  # The detailed trace analysis report
    is_general: bool = False
    environment: EnvironmentFingerprint | None = None
    agent_id: str | None = None
    edit_summary: dict[str, Any] | None = None  # {preserved_sections, changed_sections, notes}
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "evolution_type": self.evolution_type.value,
            "original_content": self.original_content,
            "proposed_content": self.proposed_content,
            "diff": self.diff,
            "score": self.score,
            "reasoning": self.reasoning,
            "task_context": self.task_context,
            "trajectory": self.trajectory,
            "is_general": self.is_general,
            "environment": self.environment.to_dict() if self.environment else None,
            "agent_id": self.agent_id,
            "edit_summary": self.edit_summary,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ExecutionAnalysis:
    """Lightweight execution analysis (按需调用).

    Simplified from OpenSpace's complex analysis system.
    Only triggered when:
    1. error is None but user reports failure
    2. success_rate drops significantly
    3. Manual trigger for investigation
    """

    skill_id: str
    task_id: str
    success: bool
    error_message: str = ""
    root_cause: str = ""  # LLM-analyzed root cause
    suggested_fix: str = ""  # LLM-suggested fix
    task_context: str = ""  # Intent context of the subagent/task
    analyzed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "task_id": self.task_id,
            "success": self.success,
            "error_message": self.error_message,
            "root_cause": self.root_cause,
            "suggested_fix": self.suggested_fix,
            "task_context": self.task_context,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class SkillEvidenceGroup:
    """Aggregated execution evidence for a single skill.

    Groups success and failure cases to enable evidence-driven evolution
    decisions that avoid regressions on working scenarios.
    """

    skill_id: str
    skill_name: str
    success_cases: list[ExecutionAnalysis] = field(default_factory=list)
    failure_cases: list[ExecutionAnalysis] = field(default_factory=list)
    metrics_snapshot: SkillMetrics | None = None
    common_error_patterns: list[str] = field(default_factory=list)

    # Dual-window trend data (30-day lookback for slow-degradation detection)
    trend_failure_count: int = 0

    # Evidence quality signal (0.0-1.0, higher = more consistent error pattern)
    confidence: float = 1.0

    @property
    def total_evidence(self) -> int:
        return len(self.success_cases) + len(self.failure_cases)

    @property
    def evidence_success_rate(self) -> float:
        if self.total_evidence == 0:
            return 0.0
        return len(self.success_cases) / self.total_evidence

    def has_sufficient_evidence(self, min_total: int = 3, min_failures: int = 1) -> bool:
        """Check if there is enough evidence to justify evolution.

        Also considers 30-day trend: if trend shows persistent failures
        even when the 7-day window is sparse, evidence is sufficient.
        """
        if self.total_evidence >= min_total and len(self.failure_cases) >= min_failures:
            return True
        # Trend fallback: slow-degrading skills (e.g. 1 fail/week)
        if self.trend_failure_count >= min_total and self.trend_failure_count >= min_failures:
            return True
        return False
