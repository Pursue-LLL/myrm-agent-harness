"""Cache-TTL context pruning processor.

When prompt cache TTL expires, old tool results no longer benefit from caching.
This processor trims or archives them using pure rule-based logic (zero API cost),
reducing input_tokens while preserving recoverability through context offload.

Position in Pipeline: after FilterProcessor, before CompressProcessor.
This creates a complete cache lifecycle:
  - cache hot → CompressProcessor bypasses (protect cache)
  - cache cold → CacheTtlPruneProcessor trims/archives (release wasted tokens)
  - still over threshold → CompressProcessor compresses (normal flow)

[INPUT]
- infra.schemas::CacheTtlPruneConfig, ContextCompressOffloadCallback
- infra.schemas::CacheUsageFeedback, ContextOffloadResult
- utils.token_estimation::estimate_content_tokens, estimate_message_tokens
- processors.cache_ttl_prune_helpers::* (POS: Cache TTL pruning helper layer. Keeps the processor focused on orchestration and budget decisions.)

[OUTPUT]
- CacheTtlPruneProcessor: class — Cache TTL Prune Processor with optional async archive-summary checkpoints

[POS]
Provides CacheTtlPruneProcessor for token-aware, structure-aware, restore-cost-aware,
restore-contract-backed pruning of expired tool results with scoped offload idempotency.
"""

import time
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.runnables.config import RunnableConfig

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import (
    estimate_content_tokens,
    estimate_message_tokens,
)

from ...archive_checkpoint import ArchiveSummaryService
from ...infra.cache_break_detector import get_cache_break_detector
from ...infra.schemas import (
    DEFAULT_CACHE_TTL_PRUNE_CONFIG,
    TOOL_PROTECTION_CONFIG,
    CacheTtlPruneConfig,
    CacheUsageFeedback,
    ContextCompressOffloadCallback,
    ContextOffloadResult,
    ToolProtectionConfig,
    normalize_context_offload_result,
)
from ...tracking.task_metrics import TaskMetrics, get_task_metrics
from ..base import BaseProcessor, ProcessorContext
from .cache_ttl_prune_helpers import (
    ArchiveAttempt,
    ArchiveBudgetDecision,
    EffectivePrunePolicy,
    PruneStats,
    build_archived_placeholder,
    content_to_text,
    find_assistant_cutoff,
    find_first_human_index,
    replace_tool_content,
    soft_trim_content,
)

logger = get_agent_logger(__name__)

_ArchiveAttempt = ArchiveAttempt
_ArchiveBudgetDecision = ArchiveBudgetDecision
_EffectivePrunePolicy = EffectivePrunePolicy
_PruneStats = PruneStats
_build_archived_placeholder = build_archived_placeholder
_content_to_text = content_to_text
_find_assistant_cutoff = find_assistant_cutoff
_find_first_human_index = find_first_human_index
_replace_tool_content = replace_tool_content
_soft_trim_content = soft_trim_content

_CACHE_FEEDBACK_MIN_CALLS = 2
_CACHE_FEEDBACK_MIN_INPUT_TOKENS = 4_000
_CACHE_FEEDBACK_HOT_HIT_RATE = 0.35
_CACHE_FEEDBACK_COLD_HIT_RATE = 0.12
_OFFLOAD_IDEMPOTENCY_CACHE_LIMIT = 512
_BACKOFF_NEGATIVE_NET_SAVINGS = "negative_net_savings"
_BACKOFF_HIGH_REFETCH_RATIO = "high_refetch_ratio"
_BACKOFF_HIGH_RESTORE_COST_RATIO = "high_restore_cost_ratio"
_BACKOFF_LOW_RESTORE_ROI_RATIO = "low_restore_roi_ratio"
_BACKOFF_RECOVERY_HYSTERESIS = "recovery_hysteresis"


@dataclass(frozen=True, slots=True)
class _BackoffWindow:
    reasons: tuple[str, ...] = ()
    sample_count: int = 0
    bad_signal_count: int = 0
    recovery_sample_count: int = 0


class CacheTtlPruneProcessor(BaseProcessor):
    """Rule-based pruning of tool results whose prompt cache has expired.

    Two-level progressive strategy:
    - Level 1 (soft trim): ratio >= soft_trim_ratio → head+tail preservation
    - Level 2 (archive): ratio >= hard_clear_ratio → offload full result, then replace
      with a restorable placeholder. If offload is unavailable or fails, falls back
      to soft trim and never discards the original content irreversibly.

    Protection:
    - Last N assistant turns are never pruned
    - Protected tools (TOOL_PROTECTION_CONFIG) are never pruned
    - Messages before the first HumanMessage are never pruned (init reads)
    """

    def __init__(
        self,
        config: CacheTtlPruneConfig | None = None,
        protection_config: ToolProtectionConfig | None = None,
        max_context_tokens: int = 128000,
        on_prune_offload: ContextCompressOffloadCallback | None = None,
        archive_summary_service: ArchiveSummaryService | None = None,
    ):
        self._config = config or DEFAULT_CACHE_TTL_PRUNE_CONFIG
        self._protection = protection_config or TOOL_PROTECTION_CONFIG
        self._max_context_tokens = max_context_tokens
        self._on_prune_offload = on_prune_offload
        self._archive_summary_service = archive_summary_service
        self._offload_result_cache: OrderedDict[str, ContextOffloadResult] = OrderedDict()

    @property
    def name(self) -> str:
        return "cache_ttl_prune"

    def _is_cache_expired(self, context: ProcessorContext) -> bool:
        """Determine if prompt cache has likely expired."""
        feedback = CacheUsageFeedback.from_mapping(context.metadata.get("cache_usage_feedback"))
        feedback_decision = self._cache_feedback_expired(feedback)
        if feedback_decision is not None:
            return feedback_decision

        detector = get_cache_break_detector()
        if detector is not None:
            elapsed = detector.seconds_since_last_call()
            if elapsed is not None:
                return elapsed > self._config.ttl_seconds

        last_active = context.metadata.get("last_activity_time")
        if isinstance(last_active, (int, float)):
            return (time.time() - last_active) > self._config.ttl_seconds

        return False

    def _cache_feedback_expired(self, feedback: CacheUsageFeedback | None) -> bool | None:
        """Use provider usage feedback when the business layer supplies it."""
        if feedback is None:
            return None

        if feedback.cached_tokens > 0 and feedback.cache_hit_rate >= _CACHE_FEEDBACK_HOT_HIT_RATE:
            return False

        if (
            feedback.has_stable_sample(
                min_calls=_CACHE_FEEDBACK_MIN_CALLS,
                min_input_tokens=_CACHE_FEEDBACK_MIN_INPUT_TOKENS,
            )
            and feedback.cache_hit_rate < _CACHE_FEEDBACK_COLD_HIT_RATE
        ):
            return True

        return None

    def _is_large_payload(self, content: object) -> bool:
        return (
            isinstance(content, str)
            and self._config.large_payload_fast_guard_chars > 0
            and len(content) > self._config.large_payload_fast_guard_chars
        )

    def _estimate_content_tokens_for_pruning(self, content: str | Sequence[object]) -> int:
        """Estimate payload tokens without running tokenizer on very large tool output."""
        if self._is_large_payload(content):
            return max(1, int(len(content) / 3.5))
        return estimate_content_tokens(content)

    def _estimate_message_tokens_for_pruning(self, msg: BaseMessage) -> int:
        """Estimate message tokens while protecting the prune pass from huge single payloads."""
        if not self._is_large_payload(msg.content):
            return estimate_message_tokens(msg)

        total = self._estimate_content_tokens_for_pruning(msg.content) + 4
        if isinstance(msg, ToolMessage):
            if msg.tool_call_id:
                total += max(1, int(len(msg.tool_call_id) / 3.5))
            if msg.name:
                total += max(1, int(len(msg.name) / 3.5))
        return total

    def _estimate_messages_tokens_for_pruning(self, messages: list[BaseMessage]) -> int:
        return sum(self._estimate_message_tokens_for_pruning(msg) for msg in messages)

    def _estimate_content_bytes_for_budget(self, content: str) -> int:
        """Return exact bytes for normal payloads and allocation-free estimates for huge ones."""
        if not self._is_large_payload(content):
            return len(content.encode("utf-8"))
        if content.isascii():
            return len(content)
        return len(content) * 4

    def _estimate_context_ratio(self, messages: list[BaseMessage]) -> float:
        """Estimate context usage as a ratio of the context window."""
        total_tokens = self._estimate_messages_tokens_for_pruning(messages)
        return total_tokens / self._max_context_tokens if self._max_context_tokens > 0 else 0.0

    def _is_emergency_prune(self, context: ProcessorContext) -> bool:
        """Allow bounded pruning when cache preservation would otherwise exceed the context window."""
        if self._config.emergency_prune_ratio <= 0:
            return False
        return self._estimate_context_ratio(context.messages) >= self._config.emergency_prune_ratio

    def _effective_policy(self, context: ProcessorContext) -> _EffectivePrunePolicy:
        """Back off pruning when previous archive restores made ROI poor."""
        config = self._config
        policy = _EffectivePrunePolicy(
            soft_trim_ratio=config.soft_trim_ratio,
            hard_clear_ratio=config.hard_clear_ratio,
            min_prunable_tokens=config.min_prunable_tokens,
        )
        if not context.chat_id:
            return policy

        metrics = get_task_metrics(context.chat_id)
        if metrics is None:
            return policy

        backoff_window = self._backoff_window(metrics)
        reasons = backoff_window.reasons

        if not reasons:
            return _EffectivePrunePolicy(
                soft_trim_ratio=policy.soft_trim_ratio,
                hard_clear_ratio=policy.hard_clear_ratio,
                min_prunable_tokens=policy.min_prunable_tokens,
                backoff_sample_count=backoff_window.sample_count,
                backoff_bad_signal_count=backoff_window.bad_signal_count,
                backoff_recovery_sample_count=backoff_window.recovery_sample_count,
            )

        bump = max(config.roi_soft_trim_ratio_bump, 0.0)
        return _EffectivePrunePolicy(
            soft_trim_ratio=min(policy.soft_trim_ratio + bump, 1.0),
            hard_clear_ratio=min(policy.hard_clear_ratio + bump, 1.0),
            min_prunable_tokens=max(policy.min_prunable_tokens * 2, policy.min_prunable_tokens),
            backoff_applied=True,
            backoff_reasons=reasons,
            backoff_sample_count=backoff_window.sample_count,
            backoff_bad_signal_count=backoff_window.bad_signal_count,
            backoff_recovery_sample_count=backoff_window.recovery_sample_count,
        )

    def _backoff_window(self, metrics: TaskMetrics) -> _BackoffWindow:
        """Evaluate recent cache-TTL prune ROI with minimum samples and release hysteresis."""
        config = self._config
        window_size = max(config.roi_backoff_window_size, 1)
        recent_prunes = [
            event
            for event in metrics.compression_events
            if event.compression_type == "cache_ttl_prune" and event.tokens_saved > 0
        ][-window_size:]
        sample_count = len(recent_prunes)
        if sample_count == 0:
            return _BackoffWindow()

        minimum_samples = max(config.roi_backoff_min_samples, 1)
        recovery_samples = max(config.roi_backoff_recovery_samples, minimum_samples)
        if sample_count < minimum_samples:
            if metrics.pruning_backoff_applied and sample_count < recovery_samples:
                return _BackoffWindow(
                    reasons=(_BACKOFF_RECOVERY_HYSTERESIS,),
                    sample_count=sample_count,
                    recovery_sample_count=sample_count,
                )
            return _BackoffWindow(sample_count=sample_count)

        window_start = recent_prunes[0].timestamp
        tokens_saved = sum(event.tokens_saved for event in recent_prunes)
        window_refetch_events = [
            event
            for event in metrics.refetch_events
            if event.timestamp >= window_start and event.reason == "archive_reference_read"
        ]
        window_restore_events = [
            event
            for event in metrics.archive_restore_result_events
            if event.timestamp >= window_start
        ]
        refetch_ratio = len(window_refetch_events) / sample_count if sample_count > 0 else 0.0
        restore_tokens = sum(event.estimated_tokens for event in window_restore_events)
        net_tokens_saved = tokens_saved - sum(event.estimated_tokens for event in window_refetch_events) - restore_tokens
        restore_cost_ratio = restore_tokens / tokens_saved if tokens_saved > 0 else 0.0
        restore_roi_ratio = net_tokens_saved / tokens_saved if tokens_saved > 0 else 0.0

        bad_reasons: list[str] = []
        if net_tokens_saved < 0:
            bad_reasons.append(_BACKOFF_NEGATIVE_NET_SAVINGS)
        if refetch_ratio >= config.roi_refetch_ratio_backoff:
            bad_reasons.append(_BACKOFF_HIGH_REFETCH_RATIO)
        if window_restore_events:
            if restore_cost_ratio >= config.roi_restore_cost_ratio_backoff:
                bad_reasons.append(_BACKOFF_HIGH_RESTORE_COST_RATIO)
            if restore_roi_ratio < config.roi_restore_roi_ratio_backoff:
                bad_reasons.append(_BACKOFF_LOW_RESTORE_ROI_RATIO)

        recovery_sample_count = sample_count if not bad_reasons else 0
        if not bad_reasons and metrics.pruning_backoff_applied and recovery_sample_count < recovery_samples:
            return _BackoffWindow(
                reasons=(_BACKOFF_RECOVERY_HYSTERESIS,),
                sample_count=sample_count,
                recovery_sample_count=recovery_sample_count,
            )

        return _BackoffWindow(
            reasons=tuple(bad_reasons),
            sample_count=sample_count,
            bad_signal_count=len(bad_reasons),
            recovery_sample_count=recovery_sample_count,
        )

    def _archive_budget_decision(
        self,
        *,
        stats: _PruneStats,
        offload_bytes_used: int,
        content_bytes: int,
        started_at: float,
    ) -> _ArchiveBudgetDecision:
        """Enforce bounded archive IO and wall-clock cost per pruning pass."""
        config = self._config
        if config.max_prune_wall_ms > 0:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            if elapsed_ms >= config.max_prune_wall_ms:
                return _ArchiveBudgetDecision(
                    allowed=False,
                    reason="wall_time_budget",
                )
        if config.max_archives_per_pass >= 0 and stats.archived >= config.max_archives_per_pass:
            return _ArchiveBudgetDecision(
                allowed=False,
                reason="archive_count_budget",
            )
        if (
            config.max_offload_bytes_per_pass >= 0
            and offload_bytes_used + content_bytes > config.max_offload_bytes_per_pass
        ):
            return _ArchiveBudgetDecision(
                allowed=False,
                reason="offload_bytes_budget",
            )
        return _ArchiveBudgetDecision(allowed=True)

    async def should_process(self, context: ProcessorContext) -> bool:
        emergency_prune = self._is_emergency_prune(context)
        if self._should_skip_for_cache_preservation(context) and not emergency_prune:
            return False

        if not emergency_prune and not self._is_cache_expired(context):
            return False

        policy = self._effective_policy(context)
        ratio = self._estimate_context_ratio(context.messages)
        if ratio < policy.soft_trim_ratio:
            return False

        first_human = _find_first_human_index(context.messages)
        cutoff = _find_assistant_cutoff(context.messages, self._config.keep_last_assistant_turns)
        prune_start = first_human if first_human is not None else len(context.messages)

        prunable_tokens = 0
        for i in range(prune_start, cutoff):
            msg = context.messages[i]
            if not isinstance(msg, ToolMessage):
                continue
            tool_name = msg.name or "unknown"
            if self._protection.prune_mode(tool_name) == "protect":
                continue
            prunable_tokens += self._estimate_message_tokens_for_pruning(msg)

        return prunable_tokens >= policy.min_prunable_tokens

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        if self._should_skip_for_cache_preservation(context) and not self._is_emergency_prune(context):
            return context

        messages = list(context.messages)
        context_messages = context.messages
        ratio = self._estimate_context_ratio(messages)
        policy = self._effective_policy(context)

        first_human = _find_first_human_index(messages)
        cutoff = _find_assistant_cutoff(messages, self._config.keep_last_assistant_turns)
        prune_start = first_human if first_human is not None else len(messages)

        before_tokens = self._estimate_messages_tokens_for_pruning(context_messages)
        stats = _PruneStats()
        started_at = time.perf_counter()
        offload_bytes_used = 0

        for i in range(prune_start, cutoff):
            if self._config.max_prune_wall_ms > 0:
                elapsed_ms = (time.perf_counter() - started_at) * 1000
                if elapsed_ms >= self._config.max_prune_wall_ms:
                    stats.record_deferred("wall_time_budget")
                    break

            msg = messages[i]
            if not isinstance(msg, ToolMessage):
                continue
            tool_name = msg.name or "unknown"
            prune_mode = self._protection.prune_mode(tool_name)
            if prune_mode == "protect":
                continue

            if not isinstance(msg.content, (str, list)):
                continue

            content = _content_to_text(msg.content)
            if not content:
                continue

            archive_deferred_reason = ""
            if prune_mode == "allow" and ratio >= policy.hard_clear_ratio:
                content_bytes = self._estimate_content_bytes_for_budget(content)
                budget_decision = self._archive_budget_decision(
                    stats=stats,
                    offload_bytes_used=offload_bytes_used,
                    content_bytes=content_bytes,
                    started_at=started_at,
                )
                if budget_decision.allowed:
                    archive_attempt = await self._try_archive_tool_message(
                        msg=msg,
                        content=content,
                        context=context,
                    )
                    if archive_attempt.archived:
                        messages[i] = _replace_tool_content(
                            msg,
                            archive_attempt.replacement_content,
                        )
                        stats.archived += 1
                        if archive_attempt.offload_reused:
                            stats.archive_reused += 1
                            stats.archive_bytes_reused += archive_attempt.stored_bytes or content_bytes
                        else:
                            stats.archive_written += 1
                            stats.archive_bytes_written += archive_attempt.stored_bytes or content_bytes
                            offload_bytes_used += content_bytes
                        stats.original_tokens += self._estimate_content_tokens_for_pruning(content)
                        ratio = self._estimate_context_ratio(messages)
                        continue

                    stats.record_offload_failure(archive_attempt.failure_kind or "temporary_failure")
                else:
                    archive_deferred_reason = budget_decision.reason
                    stats.record_archive_deferred(archive_deferred_reason)

            trimmed = self._soft_trim_replacement(content)
            if ratio >= policy.soft_trim_ratio and trimmed is not None:
                messages[i] = _replace_tool_content(msg, trimmed)
                stats.soft_trimmed += 1
                stats.original_tokens += self._estimate_content_tokens_for_pruning(content)
                if archive_deferred_reason:
                    stats.record_archive_deferred_soft_trimmed(archive_deferred_reason)
                ratio = self._estimate_context_ratio(messages)
            elif archive_deferred_reason:
                stats.record_deferred(archive_deferred_reason)

        if stats.soft_trimmed > 0 or stats.archived > 0:
            after_tokens = self._estimate_messages_tokens_for_pruning(messages)
            tokens_saved = max(0, before_tokens - after_tokens)
            context.messages = messages
            context.tokens_saved += tokens_saved
            self._record_metrics(context, tokens_saved, stats, policy)
            detector = get_cache_break_detector()
            if detector is not None:
                detector.notify_compaction()
            logger.warning(
                "[CacheTtlPrune] soft_trimmed=%d, archived=%d, offload_failed=%d, archive_deferred=%d, %d tokens saved",
                stats.soft_trimmed,
                stats.archived,
                stats.offload_failed,
                stats.archive_deferred,
                tokens_saved,
            )
        elif stats.deferred > 0 or stats.offload_failed > 0 or stats.archive_deferred > 0:
            self._record_metrics(context, 0, stats, policy)

        return context

    async def _try_archive_tool_message(
        self,
        *,
        msg: ToolMessage,
        content: str,
        context: ProcessorContext,
    ) -> _ArchiveAttempt:
        """Archive full content and replace the message with a restorable reference."""
        if self._on_prune_offload is None:
            return _ArchiveAttempt(archived=False, failure_kind="unsupported")

        tool_name = msg.name or "unknown"
        cache_key = None
        scope_id = context.chat_id
        if scope_id:
            cache_key = self._offload_cache_key(
                msg=msg,
                tool_name=tool_name,
                content=content,
                context=context,
            )
            cached_result = self._get_cached_offload_result(cache_key)
            if cached_result is not None:
                return self._build_archive_attempt(
                    tool_name=tool_name,
                    archive_path=cached_result.path,
                    content=content,
                    offload_reused=True,
                    original_bytes=cached_result.original_bytes,
                    stored_bytes=cached_result.stored_bytes,
                )

        try:
            offload_result = normalize_context_offload_result(
                await self._on_prune_offload(
                    content=content,
                    tool_name=tool_name,
                    scope_id=scope_id,
                )
            )
        except Exception as exc:
            logger.warning(
                "[CacheTtlPrune] offload failed for tool=%s: %s",
                tool_name,
                exc,
            )
            return _ArchiveAttempt(archived=False, failure_kind="temporary_failure")

        if not offload_result.succeeded:
            if offload_result.message:
                logger.warning(
                    "[CacheTtlPrune] offload denied for tool=%s kind=%s: %s",
                    tool_name,
                    offload_result.failure_kind,
                    offload_result.message,
                )
            return _ArchiveAttempt(
                archived=False,
                failure_kind=offload_result.failure_kind or "temporary_failure",
            )

        if self._archive_summary_service is not None:
            runnable_config = context.metadata.get("runnable_config")
            config = runnable_config if isinstance(runnable_config, RunnableConfig) else None
            self._archive_summary_service.dispatch(
                tool_name=tool_name,
                content=content,
                archive_path=offload_result.path,
                chat_id=context.chat_id,
                summarizer_llm=context.summarizer_llm or context.llm,
                tool_call_id=getattr(msg, "tool_call_id", None),
                runnable_config=config,
            )

        if cache_key is not None:
            self._remember_successful_offload(cache_key, offload_result)
        return self._build_archive_attempt(
            tool_name=tool_name,
            archive_path=offload_result.path,
            content=content,
            offload_reused=offload_result.reused,
            original_bytes=offload_result.original_bytes,
            stored_bytes=offload_result.stored_bytes,
        )

    def _offload_cache_key(
        self,
        *,
        msg: ToolMessage,
        tool_name: str,
        content: str,
        context: ProcessorContext,
    ) -> str:
        """Build a scoped idempotency key for retry-safe archive offload."""
        content_sha = sha256(content.encode("utf-8")).hexdigest()
        parts = [
            context.chat_id or "",
            tool_name,
            msg.tool_call_id or "",
            str(len(content)),
            content_sha,
        ]
        return "\0".join(parts)

    def _get_cached_offload_result(self, cache_key: str) -> ContextOffloadResult | None:
        result = self._offload_result_cache.get(cache_key)
        if result is None:
            return None
        self._offload_result_cache.move_to_end(cache_key)
        return result

    def _remember_successful_offload(
        self,
        cache_key: str,
        offload_result: ContextOffloadResult,
    ) -> None:
        self._offload_result_cache[cache_key] = offload_result
        self._offload_result_cache.move_to_end(cache_key)
        while len(self._offload_result_cache) > _OFFLOAD_IDEMPOTENCY_CACHE_LIMIT:
            self._offload_result_cache.popitem(last=False)

    def _build_archive_attempt(
        self,
        *,
        tool_name: str,
        archive_path: str,
        content: str,
        offload_reused: bool,
        original_bytes: int = 0,
        stored_bytes: int = 0,
    ) -> _ArchiveAttempt:
        placeholder = _build_archived_placeholder(
            tool_name=tool_name,
            archive_path=archive_path,
            content=content,
            original_tokens=self._estimate_content_tokens_for_pruning(content),
            original_chars=len(content),
        )
        return _ArchiveAttempt(
            archived=True,
            replacement_content=placeholder,
            offload_reused=offload_reused,
            original_bytes=original_bytes,
            stored_bytes=stored_bytes,
        )

    def _soft_trim_replacement(self, content: str) -> str | None:
        """Build a soft-trimmed replacement without mutating the source message."""
        trimmed = _soft_trim_content(content, self._config)
        return trimmed

    def _record_metrics(
        self,
        context: ProcessorContext,
        tokens_saved: int,
        stats: _PruneStats,
        policy: _EffectivePrunePolicy,
    ) -> None:
        """Record task-level pruning metrics when a chat-scoped metrics object exists."""
        if not context.chat_id:
            return
        if tokens_saved <= 0 and stats.deferred == 0 and stats.offload_failed == 0 and stats.archive_deferred == 0:
            return
        metrics = get_task_metrics(context.chat_id)
        if metrics is None:
            return
        metrics.record_compression(
            tokens_saved=tokens_saved,
            compression_type="cache_ttl_prune",
            details=(
                f"Cache TTL prune archived={stats.archived}, "
                f"soft_trimmed={stats.soft_trimmed}, offload_failed={stats.offload_failed}, "
                f"archive_written={stats.archive_written}, archive_reused={stats.archive_reused}, "
                f"unmodified_deferred={stats.deferred}, archive_deferred={stats.archive_deferred}, "
                f"archive_deferred_soft_trimmed={stats.archive_deferred_soft_trimmed}, "
                f"original_tokens={stats.original_tokens}, backoff={policy.backoff_applied}, "
                f"backoff_reasons={','.join(policy.backoff_reasons)}, "
                f"backoff_samples={policy.backoff_sample_count}, "
                f"backoff_bad_signals={policy.backoff_bad_signal_count}, "
                f"backoff_recovery_samples={policy.backoff_recovery_sample_count}"
            ),
            group_count=stats.archived + stats.soft_trimmed,
            archive_count=stats.archived,
            soft_trimmed_count=stats.soft_trimmed,
            offload_failed_count=stats.offload_failed,
            offload_failure_kinds=stats.offload_failure_kinds,
            deferred_count=stats.deferred,
            deferred_reasons=stats.deferred_reasons,
            archive_deferred_count=stats.archive_deferred,
            archive_deferred_reasons=stats.archive_deferred_reasons,
            archive_deferred_soft_trimmed_count=stats.archive_deferred_soft_trimmed,
            archive_deferred_soft_trimmed_reasons=stats.archive_deferred_soft_trimmed_reasons,
            original_tokens=stats.original_tokens,
            archive_written_count=stats.archive_written,
            archive_reused_count=stats.archive_reused,
            archive_bytes_written=stats.archive_bytes_written,
            archive_bytes_reused=stats.archive_bytes_reused,
            backoff_applied=policy.backoff_applied,
            backoff_reasons=list(policy.backoff_reasons),
            effective_soft_trim_ratio=policy.soft_trim_ratio,
            effective_hard_clear_ratio=policy.hard_clear_ratio,
            effective_min_prunable_tokens=policy.min_prunable_tokens,
            backoff_sample_count=policy.backoff_sample_count,
            backoff_bad_signal_count=policy.backoff_bad_signal_count,
            backoff_recovery_sample_count=policy.backoff_recovery_sample_count,
        )
