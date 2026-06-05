"""Data types for skill consolidation system.

Defines structured outputs for the cluster detection, LLM judgment,
and execution phases of skill consolidation.

[INPUT]
- (none)

[OUTPUT]
- ConsolidationActionType: Enum for consolidation actions (MERGE/CREATE_UMBRELLA/DEMOTE/KEEP).
- SkillCluster: A group of semantically similar skills identified as merge candidates.
- ConsolidationAction: A single consolidation action within a plan.
- ConsolidationPlan: Complete plan output from the ConsolidationJudge.
- ConsolidationReport: Post-execution report of what was actually done.

[POS]
Data types for the skill consolidation (umbrella merge) system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class ConsolidationActionType(StrEnum):
    """Type of consolidation action to perform on a cluster."""

    MERGE = "merge"
    """Merge siblings into an existing broader skill (expand it)."""

    CREATE_UMBRELLA = "create_umbrella"
    """Create a new class-level umbrella skill absorbing all cluster members."""

    DEMOTE = "demote"
    """Move narrow skill content into support files (references/templates/scripts)."""

    KEEP = "keep"
    """No action needed — cluster members are already well-organized."""


@dataclass(frozen=True, slots=True)
class SkillCluster:
    """A group of semantically similar skills identified as merge candidates.

    Produced by ClusterDetector. Each cluster is evaluated independently
    by the ConsolidationJudge.
    """

    cluster_id: str
    """Unique identifier for this cluster (e.g. 'cluster-deploy')."""

    skill_names: tuple[str, ...]
    """Names of skills in this cluster."""

    shared_domain: str
    """The shared domain/topic keyword (e.g. 'deployment', 'git-operations')."""

    avg_similarity: float
    """Average pairwise embedding similarity within the cluster."""

    representative_keywords: tuple[str, ...] = ()
    """Top keywords shared across cluster members."""


@dataclass(frozen=True, slots=True)
class ConsolidationAction:
    """A single consolidation action within a plan.

    Represents one operation the executor should perform.
    """

    action_type: ConsolidationActionType
    """What to do with this cluster."""

    target_skill: str
    """The umbrella skill name (existing for MERGE, new for CREATE_UMBRELLA)."""

    source_skills: tuple[str, ...]
    """Skills to be absorbed/demoted."""

    reasoning: str
    """LLM's explanation for this decision."""

    umbrella_description: str = ""
    """Proposed description for the umbrella (CREATE_UMBRELLA only)."""

    umbrella_content_outline: str = ""
    """High-level content outline for the umbrella (CREATE_UMBRELLA only)."""

    demote_target_dir: str = "references"
    """Subdirectory for DEMOTE action (references/templates/scripts)."""


@dataclass(slots=True)
class ConsolidationPlan:
    """Complete consolidation plan output from the ConsolidationJudge.

    Generated in dry-run mode for user preview before execution.
    """

    actions: list[ConsolidationAction] = field(default_factory=list)
    """Ordered list of consolidation actions."""

    total_skills_affected: int = 0
    """Total number of skills that will be modified or archived."""

    estimated_reduction: int = 0
    """Net reduction in active skill count after execution."""

    preview_summary: str = ""
    """Human-readable summary for GUI display."""

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When this plan was generated."""

    @property
    def is_empty(self) -> bool:
        return len(self.actions) == 0

    @property
    def merge_count(self) -> int:
        return sum(1 for a in self.actions if a.action_type == ConsolidationActionType.MERGE)

    @property
    def create_count(self) -> int:
        return sum(1 for a in self.actions if a.action_type == ConsolidationActionType.CREATE_UMBRELLA)

    @property
    def demote_count(self) -> int:
        return sum(1 for a in self.actions if a.action_type == ConsolidationActionType.DEMOTE)


@dataclass(frozen=True, slots=True)
class ConsolidationResult:
    """Result of executing a single ConsolidationAction."""

    action: ConsolidationAction
    """The action that was executed."""

    success: bool
    """Whether execution succeeded."""

    umbrella_skill_path: str = ""
    """Path to the resulting umbrella skill (if created/modified)."""

    archived_skills: tuple[str, ...] = ()
    """Skills that were archived (marked merged_into)."""

    error: str = ""
    """Error message if success is False."""


@dataclass(slots=True)
class ConsolidationReport:
    """Post-execution report of a complete consolidation run."""

    results: list[ConsolidationResult] = field(default_factory=list)
    """Per-action results."""

    skills_before: int = 0
    """Active skill count before consolidation."""

    skills_after: int = 0
    """Active skill count after consolidation."""

    total_archived: int = 0
    """Total skills archived (merged into umbrellas)."""

    total_created: int = 0
    """Total new umbrella skills created."""

    duration_seconds: float = 0.0
    """Wall-clock time for the entire consolidation run."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the consolidation run started."""

    @property
    def net_reduction(self) -> int:
        return self.skills_before - self.skills_after

    @property
    def success_count(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failure_count(self) -> int:
        return sum(1 for r in self.results if not r.success)

    def to_summary(self) -> str:
        """Generate human-readable summary for GUI display."""
        if not self.results:
            return "No consolidation actions were needed."
        lines = [
            f"Consolidated {self.total_archived} skills into {self.success_count} umbrellas.",
            f"Active skills: {self.skills_before} → {self.skills_after} (reduced by {self.net_reduction}).",
        ]
        if self.failure_count > 0:
            lines.append(f"⚠ {self.failure_count} action(s) failed.")
        return "\n".join(lines)
