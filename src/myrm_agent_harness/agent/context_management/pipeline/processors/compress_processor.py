"""Compress processor.

Compresses old tool calls when total context exceeds threshold.

Strategy:
1. Offload original content via on_compress_offload before compressing (lossy but traceable)
2. Three-tier strategy (Dedup/Truncate/Remove)
3. Keep N most recent complete calls as few-shot examples
4. Compress oldest first to preserve fresh examples for the model
5. Use tool-specific templates preserving identifiers and metadata
6. Cold Cache Drain Architecture: bypass when cache is hot to protect Prompt Cache
7. Anti-Thrashing: skip compression when recent attempts saved <10% each (streak >= 2),
   with 90% hard-limit safety net to prevent OOM

IMPORTANT: Self-update reminder: once this file is updated, also update:
1. agent/context_management/PROMPT_CACHE_PRACTICE.md §4.1

[INPUT]
- (none)

[OUTPUT]
- CompressProcessor: class — Compress Processor

[POS]
Provides CompressProcessor with Hot Cache Bypass and Anti-Thrashing protection.
"""

import time
from dataclasses import replace

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ...infra.context_budget import calculate_context_budget
from ...infra.schemas import (
    ContextCompressEvictionCallback,
    ContextCompressOffloadCallback,
    ContextConfig,
    ContextSnapshotCallback,
)
from ...strategies.compactor import compress_messages_async
from ...strategies.smart_fallback import apply_smart_fallback
from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)


class CompressProcessor(BaseProcessor):
    """Compress processor.

    When total context exceeds threshold:
    1. Locate all tool call pairs (AIMessage + ToolMessage)
    2. Keep N most recent complete calls (few-shot examples)
    3. Replace old tool results with compact format (identifier + metadata)

    Cold Cache Drain Architecture (Hot Cache Bypass):
    - If cache is "hot" (last activity < 5 min) and below 90% physical limit,
      intercept and mark compaction_debt_pending to avoid breaking Prompt Cache

    Anti-Thrashing Protection:
    - If last 2+ compressions each saved <10%, skip compression to protect Prompt Cache
    - 90% hard-limit safety net: always compress when nearing context overflow
    - Streak resets to 0 when an effective compression (>=10% savings) occurs
    """

    def __init__(
        self,
        max_context_tokens: int = 128000,
        tool_result_evict_threshold: int = 5000,
        compress_min_save: int = 3000,
        compress_batch_rounds: int = 5,
        keep_recent_calls: int = 5,
        on_compress_offload: ContextCompressOffloadCallback | None = None,
        on_compress_eviction: ContextCompressEvictionCallback | None = None,
        on_context_snapshot: ContextSnapshotCallback | None = None,
    ):
        self._on_compress_offload = on_compress_offload
        self._on_compress_eviction = on_compress_eviction
        self._on_context_snapshot = on_context_snapshot
        self.config = ContextConfig(
            max_context_tokens=max_context_tokens,
            tool_result_evict_threshold=tool_result_evict_threshold,
            compress_min_save=compress_min_save,
            compress_batch_rounds=compress_batch_rounds,
            keep_recent_calls=keep_recent_calls,
        )

    _ECO_KEEP_RECENT_REDUCTION: int = 2
    _ECO_THRESHOLD_FACTOR: float = 0.80
    _HOT_CACHE_WINDOW_SECONDS: float = 300.0  # 5 minutes
    _ANTI_THRASHING_STREAK_LIMIT: int = 2
    _EFFECTIVE_SAVINGS_THRESHOLD: float = 0.10
    _SAFETY_NET_RATIO: float = 0.90

    @property
    def name(self) -> str:
        return "compress"

    def _is_eco_mode(self, context: ProcessorContext) -> bool:
        """Check if eco mode is active (budget pressure signal from business layer)."""
        return bool(context.metadata.get("eco_mode", False))

    def _should_bypass_for_hot_cache(self, context: ProcessorContext, current_tokens: int) -> bool:
        """Check whether to bypass compression due to hot cache."""
        max_tokens = self.config.max_context_tokens or 128000
        if current_tokens >= max_tokens * 0.90:
            return False  # MUST compress synchronously to avoid OOM

        last_active = context.metadata.get("last_activity_time")
        return isinstance(last_active, (int, float)) and (time.time() - last_active < self._HOT_CACHE_WINDOW_SECONDS)

    async def should_process(self, context: ProcessorContext) -> bool:
        """Determine whether compression is needed (with hot cache bypass).

        Eco mode: when metadata['eco_mode'] is True, dynamic threshold is reduced by 20%.
        """
        total_tokens = estimate_messages_tokens(context.messages)
        cfg = self.config
        eco_mode = self._is_eco_mode(context)

        turn_count = sum(1 for m in context.messages if m.type == "human")

        budget = calculate_context_budget(context.messages, cfg)
        dynamic_threshold, _ = budget.calculate_dynamic_thresholds(
            turn_count=turn_count,
            estimated_remaining_turns=10,
        )

        if eco_mode:
            dynamic_threshold = int(dynamic_threshold * self._ECO_THRESHOLD_FACTOR)

        if dynamic_threshold != cfg.compress_threshold:
            eco_tag = " [Eco]" if eco_mode else ""
            logger.info(
                "Dynamic threshold: %d -> %d%s (turns=%d, tokens=%d)",
                cfg.compress_threshold,
                dynamic_threshold,
                eco_tag,
                turn_count,
                total_tokens,
            )

        if total_tokens < dynamic_threshold:
            return False

        # --- Anti-Thrashing: skip if recent compressions were ineffective ---
        streak = 0
        if context.chat_id:
            from ...tracking.task_metrics import get_task_metrics

            metrics = get_task_metrics(context.chat_id)
            if metrics:
                streak = metrics.compression_ineffective_streak
        if streak >= self._ANTI_THRASHING_STREAK_LIMIT:
            max_tokens = cfg.max_context_tokens or 128000
            if total_tokens < max_tokens * self._SAFETY_NET_RATIO:
                logger.info(
                    "[Compress] Anti-thrashing: skipping (streak=%d, tokens=%d < 90%% hard limit)",
                    streak,
                    total_tokens,
                )
                return False
            logger.warning(
                "[Compress] Anti-thrashing overridden by 90%% safety net (streak=%d, tokens=%d)",
                streak,
                total_tokens,
            )

        # --- Cold Cache Drain Architecture (Hot Cache Bypass) ---
        if self._should_bypass_for_hot_cache(context, total_tokens):
            logger.info(
                "[Compress] Hot cache bypass (tokens=%d), marking compaction_debt_pending",
                total_tokens,
            )
            context.metadata["compaction_debt_pending"] = True
            from ...tracking.task_metrics import get_task_metrics

            if context.chat_id:
                metrics = get_task_metrics(context.chat_id)
                if metrics:
                    metrics.compaction_debt_pending = True
            return False

        max_window = cfg.max_context_tokens or 128000
        ratio = total_tokens / max_window
        logger.info(
            "[Compress] triggered: tokens=%d, threshold=%d, max_window=%d, ratio=%.1f%%",
            total_tokens,
            dynamic_threshold,
            max_window,
            ratio * 100,
        )
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        """Execute compression."""
        # Prompt Cache preservation: Skip compress during Resume or HITL session
        if self._should_skip_for_cache_preservation(context):
            logger.info(
                "[Compress] Skipped for Prompt Cache preservation (is_resume=%s, hitl_session_active=%s)",
                context.is_resume,
                context.merged_context.get("hitl_session_active"),
            )
            return context

        original_tokens = estimate_messages_tokens(context.messages)

        budget = calculate_context_budget(context.messages, self.config)
        dynamic_min_save = budget.get_dynamic_compress_min_save()

        if dynamic_min_save != self.config.compress_min_save:
            remaining_ratio = budget.remaining_ratio if budget.remaining_ratio is not None else 1.0
            logger.info(
                "Dynamic compress_min_save: %d -> %d (remaining %.1f%%)",
                self.config.compress_min_save,
                dynamic_min_save,
                remaining_ratio * 100,
            )

        if self._on_context_snapshot:
            try:
                snapshot_path = await self._on_context_snapshot(
                    messages=context.messages,
                    chat_id=context.chat_id,
                    user_id=context.user_id,
                )
                if snapshot_path:
                    context.metadata["context_snapshot_path"] = snapshot_path
                    logger.info("[ContextSnapshot] saved to %s", snapshot_path)
            except Exception as exc:
                logger.warning("Context snapshot failed (non-blocking): %s", exc)

        effective_config = self.config
        eco_mode = self._is_eco_mode(context)
        if eco_mode:
            eco_keep = max(2, self.config.keep_recent_calls - self._ECO_KEEP_RECENT_REDUCTION)
            effective_config = replace(self.config, keep_recent_calls=eco_keep)
            logger.info(
                "[Eco] keep_recent_calls: %d -> %d",
                self.config.keep_recent_calls,
                eco_keep,
            )

        context.messages, saved = await compress_messages_async(
            context.messages,
            dynamic_min_save=dynamic_min_save,
            config=effective_config,
            on_compress_offload=self._on_compress_offload,
            on_compress_eviction=self._on_compress_eviction,
            chat_id=context.chat_id,
            user_id=context.user_id,
            failed_tool_call_ids=_extract_failed_tool_call_ids(context),
            focus_files=_extract_focus_files(context),
            focus_modules=_extract_focus_modules(context),
            user_goal_hint=_extract_user_goal_hint(context),
        )

        after_compress_tokens = estimate_messages_tokens(context.messages)
        if after_compress_tokens >= self.config.max_context_tokens * 0.95:
            logger.warning(
                "Still at %d tokens after compression, applying smart fallback",
                after_compress_tokens,
            )
            context.messages, fallback_saved = await apply_smart_fallback(
                context.messages, max_tokens=int(self.config.max_context_tokens * 0.9)
            )
            saved += fallback_saved

        context.tokens_saved += saved
        new_tokens = estimate_messages_tokens(context.messages)
        savings_pct = saved / original_tokens if original_tokens > 0 else 0

        boundary_idx = self._find_compress_boundary(context.messages)
        if boundary_idx >= 0:
            context.metadata["last_compress_boundary_index"] = boundary_idx

        compression_count = context.metadata.get("compression_count", 0) + 1
        context.metadata["compression_count"] = compression_count

        logger.info(
            "[Compress] done | saved: %d tokens (%d -> %d, %.1f%%) | boundary: #%s | count: %d",
            saved,
            original_tokens,
            new_tokens,
            savings_pct * 100,
            boundary_idx if boundary_idx >= 0 else "N/A",
            compression_count,
        )

        # Anti-thrashing: track compression effectiveness (persisted in TaskMetrics)
        if context.chat_id:
            from ...tracking.task_metrics import get_task_metrics as _get_metrics

            metrics = _get_metrics(context.chat_id)
            if metrics:
                if savings_pct >= self._EFFECTIVE_SAVINGS_THRESHOLD:
                    metrics.compression_ineffective_streak = 0
                else:
                    metrics.compression_ineffective_streak += 1
                context.metadata["compression_ineffective_streak"] = metrics.compression_ineffective_streak

        from ...infra.cache_break_detector import get_cache_break_detector

        detector = get_cache_break_detector()
        if detector is not None:
            detector.notify_compaction()

        from ...strategies.pre_compact_context import apply_pre_compact_after_protected_head

        context.messages = apply_pre_compact_after_protected_head(context.messages, context=context)

        return context

    def _find_compress_boundary(self, messages: list[BaseMessage]) -> int:
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if msg.type == "tool" and not self._is_compressed(msg):
                return i
        return -1

    def _is_compressed(self, tool_msg: BaseMessage) -> bool:
        content = str(tool_msg.content)
        return content.startswith("COMPACTED:")


def _extract_failed_tool_call_ids(context: ProcessorContext) -> frozenset[str]:
    raw_intent = context.metadata.get("compression_intent")
    if not isinstance(raw_intent, dict):
        return frozenset()

    raw_failed_ids = raw_intent.get("failed_tool_call_ids")
    if not isinstance(raw_failed_ids, list):
        return frozenset()

    return frozenset(tool_call_id for tool_call_id in raw_failed_ids if isinstance(tool_call_id, str) and tool_call_id)


def _extract_focus_files(context: ProcessorContext) -> frozenset[str]:
    raw_intent = context.metadata.get("compression_intent")
    if not isinstance(raw_intent, dict):
        return frozenset()

    raw_focus_files = raw_intent.get("focus_files")
    if not isinstance(raw_focus_files, list):
        return frozenset()

    return frozenset(file_path for file_path in raw_focus_files if isinstance(file_path, str) and file_path)


def _extract_focus_modules(context: ProcessorContext) -> frozenset[str]:
    raw_intent = context.metadata.get("compression_intent")
    if not isinstance(raw_intent, dict):
        return frozenset()

    raw_focus_modules = raw_intent.get("focus_modules")
    if not isinstance(raw_focus_modules, list):
        return frozenset()

    return frozenset(module_name for module_name in raw_focus_modules if isinstance(module_name, str) and module_name)


def _extract_user_goal_hint(context: ProcessorContext) -> str:
    raw_intent = context.metadata.get("compression_intent")
    if not isinstance(raw_intent, dict):
        return ""

    raw_goal_hint = raw_intent.get("user_goal_hint")
    if not isinstance(raw_goal_hint, str):
        return ""
    return raw_goal_hint.strip()
