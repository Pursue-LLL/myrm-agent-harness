"""Archive restore runtime budget evaluation.

[INPUT]
- infra.archive_reference::extract_context_archive_session_id, is_context_archive_path_for_session (POS: 归档路径会话归属判断)
- tracking.archive_restore::* (POS: 归档恢复预算与扁平指引 DTO)
- tracking.task_metrics_registry::get_task_metrics (POS: 任务指标注册表查询)

[OUTPUT]
- record_archive_refetch_for_path: records archive restore reads and restore outcomes.
- evaluate_archive_refetch_for_path: evaluates archive restore session and budget guards and records restore outcomes.

[POS]
Archive restore runtime guard. Applies session ownership and per-task restore budgets before archived content is exposed, and records allow/block restore outcomes for task health aggregation.
"""

from myrm_agent_harness.agent.context_management.infra.archive_reference import (
    extract_context_archive_session_id,
    is_context_archive_path_for_session,
)

from .archive_restore import (
    DEFAULT_ARCHIVE_RESTORE_BUDGET_POLICY,
    ArchiveRefetchDecision,
    ArchiveRestoreBudgetPolicy,
    ArchiveRestoreGuidance,
    build_archive_restore_guidance,
)
from .task_metrics_model import TaskMetrics
from .task_metrics_registry import get_task_metrics


def record_archive_refetch_for_path(
    path: str,
    estimated_tokens: int,
    policy: ArchiveRestoreBudgetPolicy | None = None,
) -> bool:
    """Record a refetch event when an archived context payload is read."""
    return evaluate_archive_refetch_for_path(path, estimated_tokens, policy=policy).recorded


def record_archive_restore_result_for_path(
    path: str,
    *,
    restore_arg: str,
    start_line: int,
    end_line: int,
    restored_line_count: int,
    estimated_tokens: int,
    restored_bytes: int,
    current_chat_id: str | None = None,
) -> None:
    """Record successful archive range materialization without storing restored content."""
    chat_id = current_chat_id or extract_context_archive_session_id(path)
    if chat_id is None:
        return
    metrics = get_task_metrics(chat_id)
    if metrics is None:
        return
    metrics.record_archive_restore_result(
        archive_path=path,
        restore_arg=restore_arg,
        start_line=start_line,
        end_line=end_line,
        restored_line_count=restored_line_count,
        estimated_tokens=estimated_tokens,
        restored_bytes=restored_bytes,
    )


def evaluate_archive_refetch_for_path(
    path: str,
    estimated_tokens: int,
    current_chat_id: str | None = None,
    policy: ArchiveRestoreBudgetPolicy | None = None,
    is_range_read: bool = False,
    record_allowed: bool = True,
) -> ArchiveRefetchDecision:
    """Evaluate and record an archived context read with session and budget guards."""
    chat_id = extract_context_archive_session_id(path)
    if chat_id is None:
        return ArchiveRefetchDecision(is_archive_path=False, allowed=True, recorded=False)
    metrics = get_task_metrics(current_chat_id or chat_id)
    if current_chat_id and not is_context_archive_path_for_session(path, current_chat_id):
        decision = ArchiveRefetchDecision(
            is_archive_path=True,
            allowed=False,
            recorded=False,
            reason="archive_refetch_session_mismatch",
            message="Archived context restore blocked because the archive belongs to a different session.",
            suggested_action="Use only archive references from the current session.",
            guidance=ArchiveRestoreGuidance(
                reason_label_key="archive_refetch_session_mismatch",
                severity="critical",
            ),
        )
        if metrics is not None:
            metrics.record_archive_restore_blocked(
                reason=decision.reason,
                archive_path=path,
                estimated_tokens=estimated_tokens,
                message=decision.message,
                suggested_action=decision.suggested_action,
                guidance=decision.guidance,
            )
            _record_archive_restore_outcome(
                metrics,
                decision,
                archive_path=path,
                estimated_tokens=estimated_tokens,
                is_range_read=is_range_read,
            )
        return decision

    active_policy = policy or (
        metrics.archive_restore_budget_policy
        if metrics is not None
        else DEFAULT_ARCHIVE_RESTORE_BUDGET_POLICY
    )
    if not is_range_read and estimated_tokens > active_policy.max_full_restore_tokens:
        decision = ArchiveRefetchDecision(
            is_archive_path=True,
            allowed=False,
            recorded=False,
            reason="archive_restore_range_required",
            message="Archived context restore blocked because full archive reads exceed the per-task full-restore limit.",
            suggested_action="Read a targeted line range from the archive reference chunk_restore_args.",
            guidance=build_archive_restore_guidance(
                path,
                reason="archive_restore_range_required",
                backoff_adjusted=metrics.pruning_backoff_applied if metrics is not None else False,
            ),
        )
        if metrics is not None:
            metrics.record_archive_restore_blocked(
                reason=decision.reason,
                archive_path=path,
                estimated_tokens=estimated_tokens,
                message=decision.message,
                suggested_action=decision.suggested_action,
                guidance=decision.guidance,
            )
            _record_archive_restore_outcome(
                metrics,
                decision,
                archive_path=path,
                estimated_tokens=estimated_tokens,
                is_range_read=is_range_read,
            )
        return decision

    if metrics is None:
        return ArchiveRefetchDecision(is_archive_path=True, allowed=True, recorded=False)

    decision = metrics.can_record_archive_refetch(path, estimated_tokens, policy=active_policy)
    if not decision.allowed:
        metrics.record_archive_restore_blocked(
            reason=decision.reason,
            archive_path=path,
            estimated_tokens=estimated_tokens,
            message=decision.message,
            suggested_action=decision.suggested_action,
            guidance=decision.guidance,
        )
        _record_archive_restore_outcome(
            metrics,
            decision,
            archive_path=path,
            estimated_tokens=estimated_tokens,
            is_range_read=is_range_read,
        )
        return decision

    if not record_allowed:
        _record_archive_restore_outcome(
            metrics,
            ArchiveRefetchDecision(is_archive_path=True, allowed=True, recorded=False),
            archive_path=path,
            estimated_tokens=estimated_tokens,
            is_range_read=is_range_read,
        )
        return ArchiveRefetchDecision(is_archive_path=True, allowed=True, recorded=False)

    metrics.record_refetch(
        reason="archive_reference_read",
        tool_name="file_read_tool",
        estimated_tokens=estimated_tokens,
        archive_path=path,
    )
    decision = ArchiveRefetchDecision(is_archive_path=True, allowed=True, recorded=True)
    _record_archive_restore_outcome(
        metrics,
        decision,
        archive_path=path,
        estimated_tokens=estimated_tokens,
        is_range_read=is_range_read,
    )
    return decision


def _record_archive_restore_outcome(
    metrics: TaskMetrics | None,
    decision: ArchiveRefetchDecision,
    *,
    archive_path: str,
    estimated_tokens: int,
    is_range_read: bool,
) -> None:
    if metrics is None:
        return
    metrics.record_archive_restore_outcome(
        outcome="allowed" if decision.allowed else "blocked",
        reason=decision.reason,
        archive_path=archive_path,
        estimated_tokens=estimated_tokens,
        recorded=decision.recorded,
        is_range_read=is_range_read,
    )


__all__ = [
    "evaluate_archive_refetch_for_path",
    "record_archive_refetch_for_path",
    "record_archive_restore_result_for_path",
]
