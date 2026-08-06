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
- infra.retention_helpers::extract_failed_tool_call_ids, extract_focus_files, extract_focus_modules, extract_user_goal_hint, effective_keep_recent_calls (POS: cross-processor retention contract)
- strategies.compactor.compactor::compress_messages_async (POS: priority-aware message compactor)
- strategies.compactor.smart_fallback::apply_smart_fallback (POS: extreme overflow fallback)

[OUTPUT]
- CompressProcessor: priority-aware compression with keep_recent ToolCallGroup protection and compression_intent consumption

[POS]
Pipeline compress stage. Offloads and compacts old tool-call groups; honors compression_intent and keep_recent_calls alignment with ActivePrune.
"""

import time
from dataclasses import replace

from langchain_core.messages import BaseMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import (
    estimate_messages_tokens,
    estimate_request_tools_tokens,
)

from ...infra.context_budget import (
    calculate_context_budget,
    estimate_processor_context_tokens,
    resolve_budget_kwargs_from_metadata,
)
from ...infra.schemas import (
    ContextCompressEvictionCallback,
    ContextCompressOffloadCallback,
    ContextConfig,
    ContextSnapshotCallback,
)
from ...infra.retention_helpers import (
    effective_keep_recent_calls,
    extract_failed_tool_call_ids,
    extract_focus_files,
    extract_focus_modules,
    extract_user_goal_hint,
)
from ...strategies.compactor.compactor import compress_messages_async
from ...strategies.compactor.smart_fallback import apply_smart_fallback
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

    _ECO_THRESHOLD_FACTOR: float = 0.80
    _HOT_CACHE_WINDOW_SECONDS: float = 300.0  # 5 minutes

    @property
    def name(self) -> str:
        return "compress"

    def _is_eco_mode(self, context: ProcessorContext) -> bool:
        """Check if eco mode is active (budget pressure signal from business layer)."""
        return bool(context.metadata.get("eco_mode", False))

    def _should_bypass_for_hot_cache(
        self, context: ProcessorContext, current_tokens: int
    ) -> bool:
        """Check whether to bypass compression due to hot cache."""
        max_tokens = self.config.max_context_tokens or 128000
        if current_tokens >= max_tokens * 0.90:
            return False  # MUST compress synchronously to avoid OOM

        last_active = context.metadata.get("last_activity_time")
        return isinstance(last_active, (int, float)) and (
            time.time() - last_active < self._HOT_CACHE_WINDOW_SECONDS
        )

    def _budget_kwargs(self, context: ProcessorContext) -> dict[str, int]:
        return resolve_budget_kwargs_from_metadata(context.metadata)

    def _estimate_context_tokens(self, context: ProcessorContext) -> int:
        return estimate_processor_context_tokens(context.messages, context.metadata)

    async def should_process(self, context: ProcessorContext) -> bool:
        """Determine whether compression is needed (with hot cache bypass).

        Eco mode: when metadata['eco_mode'] is True, dynamic threshold is reduced by 20%.
        """
        total_tokens = self._estimate_context_tokens(context)
        cfg = self.config
        eco_mode = self._is_eco_mode(context)

        turn_count = sum(1 for m in context.messages if m.type == "human")

        budget = calculate_context_budget(
            context.messages, cfg, **self._budget_kwargs(context)
        )
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

        from ...strategies.compression.compression_anti_thrash_guard import (
            should_block_automatic_compression,
        )

        max_tokens = cfg.max_context_tokens or 128000
        if should_block_automatic_compression(
            context.chat_id, total_tokens, max_tokens
        ):
            return False

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

        original_tokens = self._estimate_context_tokens(context)

        budget = calculate_context_budget(
            context.messages, self.config, **self._budget_kwargs(context)
        )
        dynamic_min_save = budget.get_dynamic_compress_min_save()

        if dynamic_min_save != self.config.compress_min_save:
            remaining_ratio = (
                budget.remaining_ratio if budget.remaining_ratio is not None else 1.0
            )
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
            eco_keep = effective_keep_recent_calls(
                keep_recent_calls=self.config.keep_recent_calls,
                eco_mode=True,
            )
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
            failed_tool_call_ids=extract_failed_tool_call_ids(context.metadata),
            focus_files=extract_focus_files(context.metadata),
            focus_modules=extract_focus_modules(context.metadata),
            user_goal_hint=extract_user_goal_hint(context.metadata),
        )

        after_compress_tokens = estimate_messages_tokens(context.messages)
        if after_compress_tokens >= self.config.max_context_tokens * 0.95:
            logger.warning(
                "Still at %d tokens after compression, applying smart fallback",
                after_compress_tokens,
            )
            context.messages, fallback_saved = await apply_smart_fallback(
                context.messages,
                max_tokens=int(self.config.max_context_tokens * 0.9),
                failed_tool_call_ids=extract_failed_tool_call_ids(context.metadata),
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
        from ...strategies.compression.compression_anti_thrash_guard import (
            record_compression_effectiveness,
        )

        record_compression_effectiveness(
            context.chat_id,
            original_tokens=original_tokens,
            tokens_saved=saved,
        )
        if context.chat_id:
            from ...tracking.task_metrics import get_task_metrics as _get_metrics

            metrics = _get_metrics(context.chat_id)
            if metrics:
                context.metadata["compression_ineffective_streak"] = (
                    metrics.compression_ineffective_streak
                )

        from ...infra.cache_break_detector import get_cache_break_detector

        detector = get_cache_break_detector()
        if detector is not None:
            detector.notify_compaction()

        from ...strategies.compactor.pre_compact_context import (
            apply_pre_compact_after_protected_head,
        )

        context.messages = apply_pre_compact_after_protected_head(
            context.messages, context=context
        )

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
