"""Memory system diagnostics — instance-level health and maintenance reports.

HealthScore: quantitative assessment using a 3+1 elastic dimension system.
MemorySnapshot: point-in-time memory counts for before/after comparison.
MaintenanceReport: aggregated result of a full maintenance cycle.
NeglectedMemory: important memories that haven't been accessed recently.

All follow framework design principles: pure data, no side effects,
frozen dataclass with .to_dict() export.

[INPUT]
- (none)

[OUTPUT]
- HealthScore: Immutable health assessment of a memory system instance.
- NeglectedMemory: class — Neglected Memory
- MemorySnapshot: Point-in-time count of active (non-archived) memories by ...
- MaintenanceReport: Aggregated result of a full maintenance cycle.
- compute_health: Compute health score from pre-collected data. Pure functi...

[POS]
Memory system diagnostics — instance-level health and maintenance reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettableMemory,
    ForgettingConfig,
    ForgettingStrategy,
)


@dataclass(frozen=True)
class HealthScore:
    """Immutable health assessment of a memory system instance.

    Mirrors the pattern of SearchSnapshot / CheckpointMetrics:
    framework provides structured data, business layer decides how to
    display, persist, or act on it.
    """

    total: int
    dimensions: dict[str, float]
    suggestions: list[str]
    has_graph: bool
    sample_size: int

    def to_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "dimensions": dict(self.dimensions),
            "suggestions": list(self.suggestions),
            "has_graph": self.has_graph,
            "sample_size": self.sample_size,
        }


_FRESHNESS_WINDOW_DAYS = 30
_COVERAGE_WINDOW_DAYS = 14
_COHERENCE_SAMPLE_LIMIT = 100

_WEIGHTS_NO_GRAPH: dict[str, float] = {
    "freshness": 0.40,
    "coverage": 0.30,
    "retention_health": 0.30,
}

_WEIGHTS_WITH_GRAPH: dict[str, float] = {
    "freshness": 0.30,
    "coverage": 0.25,
    "retention_health": 0.25,
    "coherence": 0.20,
}


@dataclass
class _HealthInput:
    """Raw data collected by MemoryManager for health computation."""

    memories: list[ForgettableMemory] = field(default_factory=list)
    type_counts: dict[str, int] = field(default_factory=dict)
    type_latest_update: dict[str, datetime | None] = field(default_factory=dict)
    coherent_count: int = 0
    coherence_sample_size: int = 0
    has_graph: bool = False
    forgetting_config: ForgettingConfig = field(default_factory=ForgettingConfig)


def compute_health(data: _HealthInput) -> HealthScore:
    """Compute health score from pre-collected data. Pure function, no IO."""
    total_memories = len(data.memories)
    if total_memories == 0:
        return HealthScore(
            total=100,
            dimensions={},
            suggestions=[],
            has_graph=data.has_graph,
            sample_size=0,
        )

    dims: dict[str, float] = {}
    suggestions: list[str] = []
    now = datetime.now(UTC)
    cutoff_fresh = now - timedelta(days=_FRESHNESS_WINDOW_DAYS)
    cutoff_coverage = now - timedelta(days=_COVERAGE_WINDOW_DAYS)

    fresh_count = 0
    for mem in data.memories:
        ref_time = mem.last_accessed_at or mem.created_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=UTC)
        if ref_time >= cutoff_fresh:
            fresh_count += 1

    freshness = fresh_count / total_memories
    dims["freshness"] = round(freshness, 4)
    if freshness < 0.5:
        suggestions.append("Many memories are stale — consider running maintenance")

    types_with_data = sum(1 for c in data.type_counts.values() if c > 0)
    if types_with_data == 0:
        coverage = 1.0
    else:
        types_recently_updated = 0
        for type_name, latest in data.type_latest_update.items():
            if data.type_counts.get(type_name, 0) == 0:
                continue
            if latest is not None:
                lt = latest if latest.tzinfo else latest.replace(tzinfo=UTC)
                if lt >= cutoff_coverage:
                    types_recently_updated += 1
        coverage = types_recently_updated / types_with_data

    dims["coverage"] = round(coverage, 4)
    if coverage < 0.5:
        stale_types = [
            t
            for t, c in data.type_counts.items()
            if c > 0
            and (
                data.type_latest_update.get(t) is None or _ensure_utc(data.type_latest_update[t]) < cutoff_coverage  # type: ignore[arg-type]
            )
        ]
        if stale_types:
            suggestions.append(
                f"Memory types lacking recent updates: {', '.join(stale_types)}"
            )

    strategy = ForgettingStrategy(data.forgetting_config)
    safe_count = 0
    for mem in data.memories:
        score = strategy.calculate_retention_score(mem, relation_count=0)
        if not score.should_forget:
            safe_count += 1

    retention = safe_count / total_memories
    dims["retention_health"] = round(retention, 4)
    if retention < 0.7:
        at_risk = total_memories - safe_count
        suggestions.append(
            f"{at_risk} memories at risk of forgetting — review importance settings"
        )

    if data.has_graph and data.coherence_sample_size > 0:
        coherence = data.coherent_count / data.coherence_sample_size
        dims["coherence"] = round(coherence, 4)
        if coherence < 0.3:
            suggestions.append(
                "Low graph connectivity — add relations between related memories"
            )

    weights = _WEIGHTS_WITH_GRAPH if data.has_graph else _WEIGHTS_NO_GRAPH
    weighted_sum = sum(dims.get(dim, 0.0) * w for dim, w in weights.items())
    total = round(weighted_sum * 100)
    total = max(0, min(100, total))

    return HealthScore(
        total=total,
        dimensions=dims,
        suggestions=suggestions,
        has_graph=data.has_graph,
        sample_size=total_memories,
    )


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True)
class NeglectedMemory:
    """An important memory that hasn't been accessed recently."""

    memory_id: str
    content_preview: str
    importance: float
    pinned: bool
    days_since_access: int
    memory_type: str

    def to_dict(self) -> dict[str, object]:
        return {
            "memory_id": self.memory_id,
            "content_preview": self.content_preview,
            "importance": self.importance,
            "pinned": self.pinned,
            "days_since_access": self.days_since_access,
            "memory_type": self.memory_type,
        }


def detect_neglected(
    memories: list[ForgettableMemory],
    *,
    importance_threshold: float = 0.6,
    stale_days: int = 14,
    max_items: int = 10,
) -> tuple[NeglectedMemory, ...]:
    """Find important memories that have been neglected. Pure function, no IO.

    A memory is considered neglected if:
    - pinned=True OR importance >= importance_threshold
    - AND last_accessed_at > stale_days ago (or never accessed and created > stale_days ago)
    """
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=stale_days)
    candidates: list[NeglectedMemory] = []

    for mem in memories:
        if not (
            getattr(mem, "pinned", False) or mem.importance >= importance_threshold
        ):
            continue

        ref_time = mem.last_accessed_at or mem.created_at
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=UTC)
        if ref_time >= cutoff:
            continue

        days = (now - ref_time).days
        mem_type = getattr(
            mem, "memory_type", type(mem).__name__.replace("Memory", "").lower()
        )
        content = mem.content[:100] if len(mem.content) > 100 else mem.content

        candidates.append(
            NeglectedMemory(
                memory_id=mem.id,
                content_preview=content,
                importance=mem.importance,
                pinned=getattr(mem, "pinned", False),
                days_since_access=days,
                memory_type=str(mem_type),
            )
        )

    candidates.sort(key=lambda n: n.days_since_access, reverse=True)
    return tuple(candidates[:max_items])


@dataclass(frozen=True)
class MemorySnapshot:
    """Point-in-time count of active (non-archived) memories by type.

    Collected before and after a maintenance cycle to quantify changes.
    ``total`` is a derived property to prevent inconsistency.
    """

    semantic: int
    episodic: int

    @property
    def total(self) -> int:
        return self.semantic + self.episodic

    def to_dict(self) -> dict[str, int]:
        return {
            "semantic": self.semantic,
            "episodic": self.episodic,
            "total": self.total,
        }


@dataclass(frozen=True)
class MaintenanceReport:
    """Aggregated result of a full maintenance cycle.

    Returned by MemoryManager.run_maintenance_cycle(). Business layer
    decides how to display, persist, or act on it.
    """

    consolidation_merged: int = 0
    consolidation_corrected: int = 0
    consolidation_updated: int = 0
    consolidation_errors: int = 0
    digests_evaporated: int = 0
    claims_compiled: int = 0
    forgotten_count: int = 0
    archived_count: int = 0
    blobs_swept: int = 0
    neglected_memories: tuple[NeglectedMemory, ...] = ()
    insights: tuple[str, ...] = ()
    before: MemorySnapshot | None = None
    after: MemorySnapshot | None = None
    health: HealthScore | None = None
    duration_ms: float = 0.0
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "before": self.before.to_dict() if self.before else None,
            "after": self.after.to_dict() if self.after else None,
            "consolidation": {
                "merged": self.consolidation_merged,
                "corrected": self.consolidation_corrected,
                "updated": self.consolidation_updated,
                "errors": self.consolidation_errors,
            },
            "digests": {
                "evaporated": self.digests_evaporated,
            },
            "claim_graph": {
                "compiled": self.claims_compiled,
            },
            "forgetting": {
                "forgotten": self.forgotten_count,
                "archived": self.archived_count,
            },
            "blob_gc": {
                "swept": self.blobs_swept,
            },
            "neglected": [n.to_dict() for n in self.neglected_memories],
            "insights": list(self.insights),
            "health": self.health.to_dict() if self.health else None,
            "duration_ms": self.duration_ms,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }
