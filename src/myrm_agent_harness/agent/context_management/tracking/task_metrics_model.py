"""TaskMetrics model and derived counters.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类装饰器)
- datetime::datetime (POS: Python 日期时间)
- threading::Lock (POS: Python 线程锁)
- typing::Literal (POS: Python 类型提示)
- tracking.archive_restore::* (POS: 归档恢复预算与扁平指引 DTO)
- tracking.task_metric_events::* (POS: 任务指标事件 DTO)
- utils.logger_utils::get_agent_logger (POS: Agent 日志工具)

[OUTPUT]
- TaskMetrics: task-scoped token, compression, refetch, restore outcome, and restore-block metrics.

[POS]
Task metrics domain model. Owns per-task counters, restore outcome/result aggregates, adaptive pruning
backoff aggregates, derived health inputs, and serializable metric summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Literal

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .archive_restore import (
    DEFAULT_ARCHIVE_RESTORE_BUDGET_POLICY,
    ArchiveRestoreBudgetPolicy,
)
from .task_metric_events import (
    ArchiveRestoreBlockEvent,
    ArchiveRestoreOutcomeEvent,
    ArchiveRestoreResultEvent,
    CompressionEvent,
    RefetchEvent,
    sanitize_count_map,
    sanitize_string_list,
)
from .task_metrics_restore import TaskMetricsRestoreMixin

logger = get_agent_logger(__name__)


@dataclass
class TaskMetrics(TaskMetricsRestoreMixin):
    """任务级 Token 统计"""

    task_id: str
    task_start_time: datetime = field(default_factory=datetime.now)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens_saved: int = 0
    compression_events: list[CompressionEvent] = field(default_factory=list)
    refetch_events: list[RefetchEvent] = field(default_factory=list)
    archive_restore_outcome_events: list[ArchiveRestoreOutcomeEvent] = field(default_factory=list)
    archive_restore_result_events: list[ArchiveRestoreResultEvent] = field(default_factory=list)
    archive_restore_block_events: list[ArchiveRestoreBlockEvent] = field(default_factory=list)
    compaction_debt_pending: bool = False
    compression_ineffective_streak: int = 0
    archive_restore_budget_policy: ArchiveRestoreBudgetPolicy = DEFAULT_ARCHIVE_RESTORE_BUDGET_POLICY
    archive_summary_queued_count: int = 0
    archive_summary_succeeded_count: int = 0
    archive_summary_failed_count: int = 0
    archive_summary_skipped_count: int = 0
    archive_summary_skipped_reasons: dict[str, int] = field(default_factory=dict)

    _lock: Lock = field(default_factory=Lock, repr=False)

    @property
    def tokens_per_task(self) -> int:
        """任务总 token 消耗(输入 + 输出)"""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def compression_count(self) -> int:
        """压缩事件总数"""
        return len(self.compression_events)

    @property
    def refetch_count(self) -> int:
        """重新获取事件总数"""
        return len(self.refetch_events)

    @property
    def archive_count(self) -> int:
        """Archived tool result count."""
        return sum(event.archive_count for event in self.compression_events)

    @property
    def soft_trimmed_count(self) -> int:
        """Soft-trimmed tool result count."""
        return sum(event.soft_trimmed_count for event in self.compression_events)

    @property
    def offload_failed_count(self) -> int:
        """Context offload failure count."""
        return sum(event.offload_failed_count for event in self.compression_events)

    @property
    def archive_written_count(self) -> int:
        """Archive files physically written by compression/pruning events."""
        return sum(event.archive_written_count for event in self.compression_events)

    @property
    def archive_reused_count(self) -> int:
        """Archive writes skipped because identical session content already existed."""
        return sum(event.archive_reused_count for event in self.compression_events)

    @property
    def archive_bytes_written(self) -> int:
        """Stored bytes physically written by compression/pruning archive events."""
        return sum(event.archive_bytes_written for event in self.compression_events)

    @property
    def archive_bytes_reused(self) -> int:
        """Stored bytes reused by compression/pruning archive events."""
        return sum(event.archive_bytes_reused for event in self.compression_events)

    @property
    def offload_failure_kinds(self) -> dict[str, int]:
        """Context offload failure counts grouped by failure kind."""
        counts: dict[str, int] = {}
        for event in self.compression_events:
            for kind, count in event.offload_failure_kinds.items():
                if count <= 0:
                    continue
                counts[kind] = counts.get(kind, 0) + count
        return counts

    @property
    def prune_deferred_count(self) -> int:
        """Cache-TTL pruning candidates deferred by pass budgets."""
        return sum(event.deferred_count for event in self.compression_events)

    @property
    def prune_deferred_reasons(self) -> dict[str, int]:
        """Cache-TTL pruning deferrals grouped by budget reason."""
        counts: dict[str, int] = {}
        for event in self.compression_events:
            for reason, count in event.deferred_reasons.items():
                if count <= 0:
                    continue
                counts[reason] = counts.get(reason, 0) + count
        return counts

    @property
    def archive_deferred_count(self) -> int:
        """Archive attempts deferred by pass budgets before fallback pruning."""
        return sum(event.archive_deferred_count for event in self.compression_events)

    @property
    def archive_deferred_reasons(self) -> dict[str, int]:
        """Archive deferrals grouped by budget reason."""
        counts: dict[str, int] = {}
        for event in self.compression_events:
            for reason, count in event.archive_deferred_reasons.items():
                if count <= 0:
                    continue
                counts[reason] = counts.get(reason, 0) + count
        return counts

    @property
    def archive_deferred_soft_trimmed_count(self) -> int:
        """Archive-deferred candidates that still received deterministic soft trimming."""
        return sum(event.archive_deferred_soft_trimmed_count for event in self.compression_events)

    @property
    def archive_deferred_soft_trimmed_reasons(self) -> dict[str, int]:
        """Archive-deferred soft trims grouped by budget reason."""
        counts: dict[str, int] = {}
        for event in self.compression_events:
            for reason, count in event.archive_deferred_soft_trimmed_reasons.items():
                if count <= 0:
                    continue
                counts[reason] = counts.get(reason, 0) + count
        return counts

    @property
    def archived_original_tokens(self) -> int:
        """Original token count represented by archived or trimmed payloads."""
        return sum(event.original_tokens for event in self.compression_events)

    @property
    def pruning_backoff_applied(self) -> bool:
        """Whether cache-TTL pruning has raised thresholds for poor restore ROI."""
        return any(
            event.backoff_applied for event in self.compression_events if event.compression_type == "cache_ttl_prune"
        )

    @property
    def pruning_backoff_reasons(self) -> dict[str, int]:
        """Cache-TTL pruning backoff reasons grouped by trigger."""
        counts: dict[str, int] = {}
        for event in self.compression_events:
            if event.compression_type != "cache_ttl_prune":
                continue
            for reason in event.backoff_reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts

    @property
    def pruning_effective_soft_trim_ratio(self) -> float:
        """Latest effective soft-trim ratio used by cache-TTL pruning."""
        event = self._latest_cache_ttl_prune_event()
        return event.effective_soft_trim_ratio if event is not None else 0.0

    @property
    def pruning_effective_hard_clear_ratio(self) -> float:
        """Latest effective hard-clear ratio used by cache-TTL pruning."""
        event = self._latest_cache_ttl_prune_event()
        return event.effective_hard_clear_ratio if event is not None else 0.0

    @property
    def pruning_effective_min_prunable_tokens(self) -> int:
        """Latest effective minimum prunable-token threshold used by cache-TTL pruning."""
        event = self._latest_cache_ttl_prune_event()
        return event.effective_min_prunable_tokens if event is not None else 0

    @property
    def pruning_backoff_sample_count(self) -> int:
        """Recent prune-event sample count used by the latest ROI backoff decision."""
        event = self._latest_cache_ttl_prune_event()
        return event.backoff_sample_count if event is not None else 0

    @property
    def pruning_backoff_bad_signal_count(self) -> int:
        """Recent ROI backoff trigger count used by the latest pruning decision."""
        event = self._latest_cache_ttl_prune_event()
        return event.backoff_bad_signal_count if event is not None else 0

    @property
    def pruning_backoff_recovery_sample_count(self) -> int:
        """Healthy recent prune-event sample count used to release prior ROI backoff."""
        event = self._latest_cache_ttl_prune_event()
        return event.backoff_recovery_sample_count if event is not None else 0

    @property
    def archive_refetch_count(self) -> int:
        """Refetches caused by reading archived context files."""
        return sum(1 for event in self.refetch_events if event.reason == "archive_reference_read")

    @property
    def archive_refetch_tokens(self) -> int:
        """Estimated token cost caused by archived context refetches."""
        return sum(event.estimated_tokens for event in self.refetch_events if event.reason == "archive_reference_read")

    @property
    def pruning_tokens_saved(self) -> int:
        """Tokens saved by cache-TTL pruning events."""
        return sum(
            event.tokens_saved for event in self.compression_events if event.compression_type == "cache_ttl_prune"
        )

    @property
    def pruning_net_tokens_saved(self) -> int:
        """Cache-TTL pruning savings after archive restore token costs."""
        return self.pruning_tokens_saved - self.archive_refetch_tokens - self.archive_restore_result_tokens

    @property
    def archive_restore_result_count(self) -> int:
        """Successful typed archive restore materializations."""
        return len(self.archive_restore_result_events)

    @property
    def archive_restore_result_tokens(self) -> int:
        """Estimated token cost of successful typed archive restores."""
        return sum(event.estimated_tokens for event in self.archive_restore_result_events)

    @property
    def archive_restore_result_lines(self) -> int:
        """Line count restored through typed archive restores."""
        return sum(event.restored_line_count for event in self.archive_restore_result_events)

    @property
    def archive_restore_result_bytes(self) -> int:
        """Byte count restored through typed archive restores."""
        return sum(event.restored_bytes for event in self.archive_restore_result_events)

    @property
    def pruning_restore_cost_ratio(self) -> float:
        """Typed restore tokens divided by cache-TTL pruning tokens saved."""
        if self.pruning_tokens_saved <= 0:
            return 0.0
        return self.archive_restore_result_tokens / self.pruning_tokens_saved

    @property
    def pruning_restore_roi_ratio(self) -> float:
        """Share of cache-TTL pruning savings retained after typed restores."""
        if self.pruning_tokens_saved <= 0:
            return 0.0
        return self.pruning_net_tokens_saved / self.pruning_tokens_saved

    @property
    def refetch_ratio(self) -> float:
        """重新获取比例"""
        if self.compression_count == 0:
            return 0.0
        return self.refetch_count / self.compression_count

    @property
    def compression_efficiency(self) -> float:
        """压缩效率"""
        total_with_saved = self.tokens_per_task + self.total_tokens_saved
        if total_with_saved == 0:
            return 0.0
        return self.total_tokens_saved / total_with_saved

    @property
    def net_tokens_saved(self) -> int:
        """净节省 token(节省 - 重新获取 - typed restore)"""
        refetch_tokens = sum(e.estimated_tokens for e in self.refetch_events)
        return self.total_tokens_saved - refetch_tokens - self.archive_restore_result_tokens

    @property
    def task_duration_seconds(self) -> float:
        """任务持续时间(秒)"""
        return (datetime.now() - self.task_start_time).total_seconds()

    def add_input_tokens(self, count: int) -> None:
        """添加输入 token 计数"""
        with self._lock:
            self.total_input_tokens += count

    def add_output_tokens(self, count: int) -> None:
        """添加输出 token 计数"""
        with self._lock:
            self.total_output_tokens += count

    def record_compression(
        self,
        tokens_saved: int,
        compression_type: Literal["filter", "cache_ttl_prune", "compress", "summarize"] = "compress",
        details: str = "",
        *,
        group_count: int = 0,
        dedup_tokens_saved: int = 0,
        integrity_skipped: int = 0,
        archive_count: int = 0,
        soft_trimmed_count: int = 0,
        offload_failed_count: int = 0,
        offload_failure_kinds: dict[str, int] | None = None,
        deferred_count: int = 0,
        deferred_reasons: dict[str, int] | None = None,
        archive_deferred_count: int = 0,
        archive_deferred_reasons: dict[str, int] | None = None,
        archive_deferred_soft_trimmed_count: int = 0,
        archive_deferred_soft_trimmed_reasons: dict[str, int] | None = None,
        original_tokens: int = 0,
        archive_written_count: int = 0,
        archive_reused_count: int = 0,
        archive_bytes_written: int = 0,
        archive_bytes_reused: int = 0,
        backoff_applied: bool = False,
        backoff_reasons: list[str] | tuple[str, ...] | None = None,
        effective_soft_trim_ratio: float = 0.0,
        effective_hard_clear_ratio: float = 0.0,
        effective_min_prunable_tokens: int = 0,
        backoff_sample_count: int = 0,
        backoff_bad_signal_count: int = 0,
        backoff_recovery_sample_count: int = 0,
    ) -> None:
        """记录压缩事件"""
        with self._lock:
            self.total_tokens_saved += tokens_saved
            self.compression_events.append(
                CompressionEvent(
                    timestamp=datetime.now(),
                    tokens_saved=tokens_saved,
                    compression_type=compression_type,
                    details=details,
                    group_count=group_count,
                    dedup_tokens_saved=dedup_tokens_saved,
                    integrity_skipped=integrity_skipped,
                    archive_count=archive_count,
                    soft_trimmed_count=soft_trimmed_count,
                    offload_failed_count=offload_failed_count,
                    offload_failure_kinds=sanitize_count_map(offload_failure_kinds),
                    deferred_count=max(deferred_count, 0),
                    deferred_reasons=sanitize_count_map(deferred_reasons),
                    archive_deferred_count=max(archive_deferred_count, 0),
                    archive_deferred_reasons=sanitize_count_map(archive_deferred_reasons),
                    archive_deferred_soft_trimmed_count=max(archive_deferred_soft_trimmed_count, 0),
                    archive_deferred_soft_trimmed_reasons=sanitize_count_map(archive_deferred_soft_trimmed_reasons),
                    original_tokens=original_tokens,
                    archive_written_count=max(archive_written_count, 0),
                    archive_reused_count=max(archive_reused_count, 0),
                    archive_bytes_written=max(archive_bytes_written, 0),
                    archive_bytes_reused=max(archive_bytes_reused, 0),
                    backoff_applied=backoff_applied,
                    backoff_reasons=sanitize_string_list(backoff_reasons),
                    effective_soft_trim_ratio=max(effective_soft_trim_ratio, 0.0),
                    effective_hard_clear_ratio=max(effective_hard_clear_ratio, 0.0),
                    effective_min_prunable_tokens=max(effective_min_prunable_tokens, 0),
                    backoff_sample_count=max(backoff_sample_count, 0),
                    backoff_bad_signal_count=max(backoff_bad_signal_count, 0),
                    backoff_recovery_sample_count=max(backoff_recovery_sample_count, 0),
                )
            )
        logger.warning(
            " [TaskMetrics] Compression: +%d tokens saved (type=%s, task=%s...)",
            tokens_saved,
            compression_type,
            self.task_id[:8],
        )

    def record_refetch(
        self,
        reason: str,
        tool_name: str = "",
        estimated_tokens: int = 0,
        archive_path: str = "",
    ) -> None:
        """记录重新获取事件"""
        with self._lock:
            self.refetch_events.append(
                RefetchEvent(
                    timestamp=datetime.now(),
                    reason=reason,
                    tool_name=tool_name,
                    estimated_tokens=estimated_tokens,
                    archive_path=archive_path,
                )
            )
        logger.warning(
            " [TaskMetrics] Refetch: reason=%s, tool=%s, task=%s... (refetch_ratio=%.2f)",
            reason,
            tool_name,
            self.task_id[:8],
            self.refetch_ratio,
        )

    def record_archive_summary_checkpoint(
        self,
        outcome: Literal["queued", "succeeded", "failed", "skipped"],
        *,
        reason: str = "",
    ) -> None:
        """Record background archive-summary queue outcomes."""
        with self._lock:
            if outcome == "queued":
                self.archive_summary_queued_count += 1
                return
            if outcome == "succeeded":
                self.archive_summary_succeeded_count += 1
                return
            if outcome == "failed":
                self.archive_summary_failed_count += 1
                return
            self.archive_summary_skipped_count += 1
            if reason:
                self.archive_summary_skipped_reasons[reason] = self.archive_summary_skipped_reasons.get(reason, 0) + 1

    def to_summary(self) -> str:
        """生成指标摘要"""
        return (
            f"[TaskMetrics] task={self.task_id[:8]}...\n"
            f" tokens_per_task: {self.tokens_per_task:,} "
            f"(input={self.total_input_tokens:,}, output={self.total_output_tokens:,})\n"
            f" tokens_saved: {self.total_tokens_saved:,} "
            f"(net={self.net_tokens_saved:,})\n"
            f" compression_efficiency: {self.compression_efficiency:.1%}\n"
            f" compression_count: {self.compression_count}\n"
            f" archive_count: {self.archive_count}\n"
            f" refetch_count: {self.refetch_count} "
            f"(ratio={self.refetch_ratio:.2f})\n"
            f" duration: {self.task_duration_seconds:.1f}s"
        )

    def to_dict(self) -> dict[str, object]:
        """转换为字典(用于 API 响应或日志)"""
        return {
            "task_id": self.task_id,
            "task_start_time": self.task_start_time.isoformat(),
            "tokens_per_task": self.tokens_per_task,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens_saved": self.total_tokens_saved,
            "net_tokens_saved": self.net_tokens_saved,
            "compression_efficiency": self.compression_efficiency,
            "compression_count": self.compression_count,
            "compression_events": [event.to_dict() for event in self.compression_events],
            "archive_count": self.archive_count,
            "soft_trimmed_count": self.soft_trimmed_count,
            "offload_failed_count": self.offload_failed_count,
            "archive_written_count": self.archive_written_count,
            "archive_reused_count": self.archive_reused_count,
            "archive_bytes_written": self.archive_bytes_written,
            "archive_bytes_reused": self.archive_bytes_reused,
            "offload_failure_kinds": self.offload_failure_kinds,
            "prune_deferred_count": self.prune_deferred_count,
            "prune_deferred_reasons": self.prune_deferred_reasons,
            "archive_deferred_count": self.archive_deferred_count,
            "archive_deferred_reasons": self.archive_deferred_reasons,
            "archive_deferred_soft_trimmed_count": self.archive_deferred_soft_trimmed_count,
            "archive_deferred_soft_trimmed_reasons": self.archive_deferred_soft_trimmed_reasons,
            "archived_original_tokens": self.archived_original_tokens,
            "pruning_backoff_applied": self.pruning_backoff_applied,
            "pruning_backoff_reasons": self.pruning_backoff_reasons,
            "pruning_effective_soft_trim_ratio": self.pruning_effective_soft_trim_ratio,
            "pruning_effective_hard_clear_ratio": self.pruning_effective_hard_clear_ratio,
            "pruning_effective_min_prunable_tokens": self.pruning_effective_min_prunable_tokens,
            "pruning_backoff_sample_count": self.pruning_backoff_sample_count,
            "pruning_backoff_bad_signal_count": self.pruning_backoff_bad_signal_count,
            "pruning_backoff_recovery_sample_count": self.pruning_backoff_recovery_sample_count,
            "refetch_count": self.refetch_count,
            "refetch_ratio": self.refetch_ratio,
            "archive_refetch_count": self.archive_refetch_count,
            "archive_refetch_tokens": self.archive_refetch_tokens,
            "archive_restore_requested_count": self.archive_restore_requested_count,
            "archive_restore_allowed_count": self.archive_restore_allowed_count,
            "archive_restore_blocked_count": self.archive_restore_blocked_count,
            "archive_restore_blocked_ratio": self.archive_restore_blocked_ratio,
            "archive_restore_result_count": self.archive_restore_result_count,
            "archive_restore_result_tokens": self.archive_restore_result_tokens,
            "archive_restore_result_lines": self.archive_restore_result_lines,
            "archive_restore_result_bytes": self.archive_restore_result_bytes,
            "pruning_restore_cost_ratio": self.pruning_restore_cost_ratio,
            "pruning_restore_roi_ratio": self.pruning_restore_roi_ratio,
            "pruning_tokens_saved": self.pruning_tokens_saved,
            "pruning_net_tokens_saved": self.pruning_net_tokens_saved,
            "archive_restore_budget": {
                "max_refetches_per_path": self.archive_restore_budget_policy.max_refetches_per_path,
                "max_refetch_tokens": self.archive_restore_budget_policy.max_refetch_tokens,
                "max_full_restore_tokens": self.archive_restore_budget_policy.max_full_restore_tokens,
            },
            "archive_summary": {
                "queued_count": self.archive_summary_queued_count,
                "succeeded_count": self.archive_summary_succeeded_count,
                "failed_count": self.archive_summary_failed_count,
                "skipped_count": self.archive_summary_skipped_count,
                "skipped_reasons": dict(self.archive_summary_skipped_reasons),
            },
            "refetch_events": [event.to_dict() for event in self.refetch_events],
            "archive_restore_outcome_events": [event.to_dict() for event in self.archive_restore_outcome_events],
            "archive_restore_result_events": [event.to_dict() for event in self.archive_restore_result_events],
            "archive_restore_block_events": [event.to_dict() for event in self.archive_restore_block_events],
            "task_duration_seconds": self.task_duration_seconds,
        }

    def _latest_cache_ttl_prune_event(self) -> CompressionEvent | None:
        for event in reversed(self.compression_events):
            if event.compression_type == "cache_ttl_prune":
                return event
        return None


__all__ = ["TaskMetrics"]
