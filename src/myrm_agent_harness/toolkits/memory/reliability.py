"""Framework-safe memory reliability contracts.

[INPUT]
myrm_agent_harness.toolkits.memory.types (POS: protocol-first memory primitives)

[OUTPUT]
MemoryArchivePayload, MemoryImportDryRunResult, MemoryReliabilityProbeResult,
MemoryRecallBenchmarkCase, MemoryRecallBenchmarkSummary: generic reliability DTOs
that product layers can persist or render.

[POS]
Framework memory reliability kit. Contains no server, UI, SaaS, or business
dependencies; applications decide how to execute, store, and expose these DTOs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MemoryReliabilityStatus = Literal["ready", "warning", "critical", "missing"]
MemoryReliabilityCategory = Literal["storage", "index", "embedding", "ledger", "deployment", "quality"]
MemoryRepairRiskLevel = Literal["safe", "confirmation_required", "manual"]
MemoryRepairExecutionStatus = Literal["completed", "blocked", "failed", "dry_run"]
MemoryArchiveSectionName = Literal["memory", "shared_context", "conversation", "replay", "audit"]
MemoryArchiveSectionStatus = Literal["ready", "empty", "partial", "unsupported"]
MemoryArchiveRestoreMode = Literal["safe_merge", "review_only", "skip"]
MemoryArchiveRestoreStatus = Literal["ready", "warning", "critical"]
MemoryArchiveRestoreSecurityVerdict = Literal["warn", "redacted", "blocked"]
MemoryArchiveRestoreItemStatus = Literal[
    "planned",
    "restored",
    "skipped",
    "conflict",
    "missing",
    "failed",
    "rolled_back",
]
MemoryImportSource = Literal[
    "native_json",
    "myrm_archive",
    "agentmemory",
    "gbrain",
    "memweaver",
    "claude_code_jsonl",
    "hermes",
    "openclaw",
    "cursor_rules",
    "codex",
    "unknown",
]
MemoryImportMappingStatus = Literal["mapped", "partially_mapped", "unsupported", "dropped"]
MemoryImportPlanStatus = Literal["planned", "skipped", "unsupported"]


class MemoryArchiveSection(BaseModel):
    """Content-safe manifest entry for one archive section."""

    name: MemoryArchiveSectionName
    status: MemoryArchiveSectionStatus
    item_count: int = Field(default=0, ge=0)
    warning_codes: list[str] = Field(default_factory=list)


class MemoryArchiveManifest(BaseModel):
    """Portable manifest for a single-sandbox memory archive."""

    format: Literal["myrm_memory_archive"] = "myrm_memory_archive"
    version: int = 1
    created_at: str
    producer: str = "myrm-agent-server"
    sections: list[MemoryArchiveSection] = Field(default_factory=list)
    content_redacted: bool = True


class MemoryArchivePayload(BaseModel):
    """Framework-safe archive payload.

    Product layers decide where the payload is stored and how users review it.
    The framework contract deliberately contains no tenant, SaaS, or GUI fields.
    """

    manifest: MemoryArchiveManifest
    data: dict[str, object] = Field(default_factory=dict)


class MemoryArchiveDryRunResult(BaseModel):
    """Content-safe archive import preview."""

    manifest: MemoryArchiveManifest
    total_items: int = Field(default=0, ge=0)
    supported_items: int = Field(default=0, ge=0)
    unsupported_items: int = Field(default=0, ge=0)
    warning_codes: list[str] = Field(default_factory=list)


class MemoryArchiveRestoreSectionPlan(BaseModel):
    """Content-safe restore plan for one archive section."""

    section: MemoryArchiveSectionName
    mode: MemoryArchiveRestoreMode = "safe_merge"
    item_count: int = Field(default=0, ge=0)
    restorable_items: int = Field(default=0, ge=0)
    review_only_items: int = Field(default=0, ge=0)
    skipped_items: int = Field(default=0, ge=0)
    conflict_items: int = Field(default=0, ge=0)
    blocked_items: int = Field(default=0, ge=0)
    warning_codes: list[str] = Field(default_factory=list)
    target_kinds: list[str] = Field(default_factory=list)


class MemoryArchiveRestoreSecurityFinding(BaseModel):
    """Content-safe security finding produced during archive restore preflight."""

    section: MemoryArchiveSectionName
    item_kind: str
    source_id: str = ""
    verdict: MemoryArchiveRestoreSecurityVerdict
    codes: list[str] = Field(default_factory=list)


class MemoryArchiveRestorePlan(BaseModel):
    """Portable archive restore plan for product-layer review surfaces."""

    version: int = 1
    plan_hash: str = ""
    status: MemoryArchiveRestoreStatus = "ready"
    total_items: int = Field(default=0, ge=0)
    restorable_items: int = Field(default=0, ge=0)
    review_only_items: int = Field(default=0, ge=0)
    skipped_items: int = Field(default=0, ge=0)
    conflict_items: int = Field(default=0, ge=0)
    blocked_items: int = Field(default=0, ge=0)
    warning_codes: list[str] = Field(default_factory=list)
    sections: list[MemoryArchiveRestoreSectionPlan] = Field(default_factory=list)
    security_findings: list[MemoryArchiveRestoreSecurityFinding] = Field(default_factory=list)


class MemoryArchiveRestoreDryRunResult(BaseModel):
    """Archive restore preview that never mutates application state."""

    manifest: MemoryArchiveManifest
    plan: MemoryArchiveRestorePlan
    payload_hash: str = ""


class MemoryArchiveRestoreMutationRef(BaseModel):
    """Content-safe mutation reference produced by archive restore or rollback."""

    section: MemoryArchiveSectionName
    item_kind: str
    source_id: str = ""
    target_id: str = ""
    status: MemoryArchiveRestoreItemStatus
    reason: str = ""


class MemoryArchiveRestoreResult(BaseModel):
    """Archive restore execution result with rollback-ready refs."""

    restore_batch_id: str
    payload_hash: str
    plan_hash: str
    restored: dict[str, int] = Field(default_factory=dict)
    total_restored: int = Field(default=0, ge=0)
    skipped_items: int = Field(default=0, ge=0)
    conflict_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)
    mutation_refs: list[MemoryArchiveRestoreMutationRef] = Field(default_factory=list)
    diagnostic_status: str | None = None
    diagnostic_run_id: str | None = None
    diagnostic_failed_count: int = Field(default=0, ge=0)


class MemoryArchiveRestoreRollbackPreview(BaseModel):
    """Content-safe rollback preview for a confirmed archive restore batch."""

    restore_batch_id: str
    total_items: int = Field(default=0, ge=0)
    reversible_items: int = Field(default=0, ge=0)
    items_by_section: dict[str, int] = Field(default_factory=dict)
    missing_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    warning_codes: list[str] = Field(default_factory=list)


class MemoryArchiveRestoreRollbackResult(BaseModel):
    """Archive restore rollback result."""

    restore_batch_id: str
    rolled_back: dict[str, int] = Field(default_factory=dict)
    total_rolled_back: int = Field(default=0, ge=0)
    missing_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    integrity_status: MemoryReliabilityStatus = "missing"
    mutation_refs: list[MemoryArchiveRestoreMutationRef] = Field(default_factory=list)


class MemoryRepairPlan(BaseModel):
    """Describes one repair option without assuming a product execution surface."""

    id: str
    label: str
    risk_level: MemoryRepairRiskLevel
    dry_run_result: str
    expected_effect: str
    requires_confirmation: bool = False
    executable: bool = False


class MemoryRepairExecutionResult(BaseModel):
    """Portable result for a repair plan execution attempt."""

    plan_id: str
    status: MemoryRepairExecutionStatus
    message: str
    audit_event_id: str | None = None
    probe_run_id: str | None = None
    changed: bool = False


class MemoryReliabilityProbeResult(BaseModel):
    """Portable probe result for memory readiness and quality checks."""

    id: str
    category: MemoryReliabilityCategory
    label: str
    status: MemoryReliabilityStatus
    evidence: str
    impact: str = ""
    next_action: str = ""
    safe_to_retry: bool = True
    duration_ms: float | None = None
    repair_plans: list[MemoryRepairPlan] = Field(default_factory=list)


class MemoryImportMappingItem(BaseModel):
    """One source bucket mapped into a framework memory bucket."""

    source_bucket: str
    target_bucket: str | None = None
    status: MemoryImportMappingStatus
    item_count: int = Field(default=0, ge=0)
    imported_count: int = Field(default=0, ge=0)
    unmapped_count: int = Field(default=0, ge=0)
    reason: str = ""


class MemoryImportDryRunSummary(BaseModel):
    """Content-safe import preview summary."""

    source: MemoryImportSource = "unknown"
    version: str = ""
    total_items: int = Field(default=0, ge=0)
    mapped_items: int = Field(default=0, ge=0)
    unmapped_items: int = Field(default=0, ge=0)
    status: MemoryReliabilityStatus = "missing"


class MemoryImportPlanItem(BaseModel):
    """One content-safe planned import action."""

    item_id: str
    memory_type: str
    status: MemoryImportPlanStatus
    reason: str = ""


class MemoryImportPlan(BaseModel):
    """Content-safe import execution plan shared by dry-run and confirm."""

    version: int = 1
    plan_hash: str = ""
    skip_duplicates: bool = True
    planned_items: int = Field(default=0, ge=0)
    skipped_items: int = Field(default=0, ge=0)
    unsupported_items: int = Field(default=0, ge=0)
    items: list[MemoryImportPlanItem] = Field(default_factory=list)


class MemoryImportDryRunResult(BaseModel):
    """Portable import dry-run result without storing memories."""

    summary: MemoryImportDryRunSummary = Field(default_factory=MemoryImportDryRunSummary)
    mappings: list[MemoryImportMappingItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    normalized_data: dict[str, list[dict[str, object]]] = Field(default_factory=dict)
    plan: MemoryImportPlan | None = None


class MemoryRecallBenchmarkCase(BaseModel):
    """A content-local recall benchmark case owned by the application layer."""

    id: str
    query: str
    expected_memory_ids: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1)


class MemoryRecallBenchmarkResult(BaseModel):
    """Result for one recall benchmark case."""

    case_id: str
    category: str = ""
    expected_found: bool
    best_rank: int | None = None
    top_k: int = Field(default=5, ge=1)
    hit_count: int = Field(default=0, ge=0)
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_ms: float = Field(default=0.0, ge=0.0)
    evidence: str = ""


class MemoryRecallBenchmarkSummary(BaseModel):
    """Aggregate recall benchmark score suitable for dashboards and SLOs."""

    case_count: int = Field(default=0, ge=0)
    passed_count: int = Field(default=0, ge=0)
    recall_at_k: float = Field(default=0.0, ge=0.0, le=1.0)
    mean_score: float = Field(default=0.0, ge=0.0, le=1.0)
    ndcg_at_k: float = Field(default=0.0, ge=0.0, le=1.0)
    mrr_score: float = Field(default=0.0, ge=0.0, le=1.0)
    precision_at_k: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_p50_ms: float = Field(default=0.0, ge=0.0)
    latency_p95_ms: float = Field(default=0.0, ge=0.0)
    status: MemoryReliabilityStatus = "missing"


def summarize_recall_benchmark(results: list[MemoryRecallBenchmarkResult]) -> MemoryRecallBenchmarkSummary:
    """Summarize benchmark results without inspecting memory content."""

    if not results:
        return MemoryRecallBenchmarkSummary()

    case_count = len(results)
    passed_count = sum(1 for result in results if result.expected_found)
    mean_score = sum(result.score for result in results) / case_count
    recall_at_k = passed_count / case_count

    precision_sum = 0.0
    ndcg_sum = 0.0
    mrr_sum = 0.0
    for r in results:
        if r.best_rank is not None and r.best_rank <= r.top_k:
            precision_sum += 1.0 / r.top_k
            relevance = 1.0 / _log2(r.best_rank + 1)
            ideal_dcg = 1.0 / _log2(2)
            ndcg_sum += relevance / ideal_dcg if ideal_dcg > 0 else 0.0
            mrr_sum += 1.0 / r.best_rank

    precision_at_k = precision_sum / case_count
    ndcg_at_k = ndcg_sum / case_count
    mrr_score = mrr_sum / case_count

    latencies = [r.latency_ms for r in results if r.latency_ms > 0]
    latency_p50 = _percentile(latencies, 50.0) if latencies else 0.0
    latency_p95 = _percentile(latencies, 95.0) if latencies else 0.0

    if recall_at_k >= 1.0:
        status: MemoryReliabilityStatus = "ready"
    elif recall_at_k >= 0.8:
        status = "warning"
    else:
        status = "critical"

    return MemoryRecallBenchmarkSummary(
        case_count=case_count,
        passed_count=passed_count,
        recall_at_k=round(recall_at_k, 4),
        mean_score=round(mean_score, 4),
        ndcg_at_k=round(ndcg_at_k, 4),
        mrr_score=round(mrr_score, 4),
        precision_at_k=round(precision_at_k, 4),
        latency_p50_ms=round(latency_p50, 2),
        latency_p95_ms=round(latency_p95, 2),
        status=status,
    )


def _log2(x: float) -> float:
    """log base 2 for NDCG scoring."""
    from math import log2

    return log2(x) if x > 0 else 0.0


def _percentile(values: list[float], p: float) -> float:
    """Simple percentile calculation without numpy dependency."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_vals):
        return sorted_vals[-1]
    return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])
