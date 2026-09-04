"""Per-step active tool-result pruning processor.

Replaces large tool results from earlier steps with compact archive
placeholders *before* the next LLM call, at zero LLM cost.

Fills the gap between ContextBudgetGuard (single result > 100K chars) and
CacheTtlPruneProcessor (cache TTL expired, ≥5min idle). During continuous
multi-step execution every step costs full token price for all prior tool
results; this processor reclaims that waste proactively.

[INPUT]
- pipeline.base::BaseProcessor, ProcessorContext (POS: Pipeline processor base class)
- infra.schemas::BUILTIN_PROTECTED_TOOLS, ContextCompressOffloadCallback (POS: Context management shared types)
- infra.schemas::ContextOffloadResult, normalize_context_offload_result (POS: Context management shared types)
- infra.archive_reference::build_tool_result_archive_reference (POS: Archive reference builder)
- tracking.task_metrics::get_task_metrics (POS: Public task metrics API)
- utils.token_estimation::estimate_content_tokens (POS: Token estimation utilities)
- utils.logger_utils::get_agent_logger (POS: Agent logger utilities)

[OUTPUT]
- ActiveToolResultPruneProcessor: per-step active pruning processor

[POS]
Per-step active tool-result pruning. Positioned after FilterProcessor
and before CacheTtlPruneProcessor in the default pipeline.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

from ...infra.archive_reference import build_tool_result_archive_reference
from ...infra.retention_helpers import effective_keep_recent_calls, find_keep_recent_prune_cutoff
from ...infra.schemas import (
    TOOL_PROTECTION_CONFIG,
    ContextCompressOffloadCallback,
    ContextOffloadResult,
    normalize_context_offload_result,
)
from ...tracking.task_metrics import get_task_metrics
from ..base import BaseProcessor, ProcessorContext

if TYPE_CHECKING:
    from ...infra.schemas import ContextCompressOffloadCallback, ContextOffloadResult

logger = get_agent_logger(__name__)


def _content_text(content: str | object) -> str | None:
    """Extract string content; returns None for non-string (multimodal) content."""
    return content if isinstance(content, str) else None


def build_memory_truncated_placeholder(
    *,
    tool_name: str,
    content: str,
    est_tokens: int,
    head_chars: int = 800,
    tail_chars: int = 400,
    reason: str | None = None,
) -> str:
    """Build a deterministic in-memory truncated placeholder preserving head & tail (DSH style)."""
    original_chars = len(content)
    reason_info = f" [{reason}]" if reason else ""
    marker = (
        f"[Tool output pruned: original size {original_chars} chars, ~{est_tokens} tokens{reason_info}. "
        f"Content pruned: {tool_name} output (~{est_tokens} tokens) truncated for recovery. "
        f"Preserved head & tail for context.]"
    )
    if original_chars <= head_chars + tail_chars:
        return marker
    head = content[:head_chars]
    tail = content[-tail_chars:] if tail_chars > 0 else ""
    return f"{head}\n\n{marker}\n\n{tail}"


def replace_tool_message_content(msg: ToolMessage, new_content: str) -> ToolMessage | None:
    """Build a replacement ToolMessage with updated content."""
    try:
        if hasattr(msg, "model_copy"):
            return msg.model_copy(update={"content": new_content})
        return msg.copy(update={"content": new_content})
    except Exception:
        logger.debug("active_prune: failed to copy ToolMessage")
        return None


async def prune_tool_results_deterministic(
    messages: list[BaseMessage],
    *,
    threshold_tokens: int = 2048,
    keep_recent_calls: int = 5,
    min_reclaim_tokens: int = 0,
    enable_memory_fallback: bool = False,
    head_chars: int = 800,
    tail_chars: int = 400,
    on_prune_offload: ContextCompressOffloadCallback | None = None,
    chat_id: str | None = None,
    placeholder_cache: dict[str, str] | None = None,
    force: bool = False,
    reason: str | None = None,
) -> tuple[list[BaseMessage], int, int]:
    """Execute deterministic tool-result pruning on messages (model-free).

    Returns:
        tuple of (new_messages, pruned_count, tokens_saved).
    """
    cutoff = find_keep_recent_prune_cutoff(messages, max(keep_recent_calls, 0))
    if cutoff <= 0:
        return messages, 0, 0

    protection_config = TOOL_PROTECTION_CONFIG
    cache = placeholder_cache if placeholder_cache is not None else {}
    thresh = max(threshold_tokens, 256)

    effective_fallback = enable_memory_fallback or force

    # Pass 1: Collect candidates and estimate prospective savings
    candidates: list[tuple[int, ToolMessage, str, str, int, str, str | None]] = []
    total_expected_savings = 0

    for i in range(cutoff):
        msg = messages[i]
        if not isinstance(msg, ToolMessage):
            continue
        tool_name = msg.name or "unknown"
        if protection_config.is_active_prune_never(tool_name):
            continue

        content_str = _content_text(msg.content)
        if content_str is None:
            continue
        est_tokens = estimate_content_tokens(content_str)
        if est_tokens <= thresh:
            continue

        content_sha = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
        cache_key = f"{msg.tool_call_id}:{content_sha}"
        cached_placeholder = cache.get(cache_key)

        if cached_placeholder is not None:
            expected_savings = est_tokens - estimate_content_tokens(cached_placeholder)
        elif on_prune_offload is not None:
            expected_savings = max(1, est_tokens - 100)
        elif effective_fallback:
            approx_ph_chars = min(len(content_str), head_chars + tail_chars + 120)
            expected_savings = max(1, est_tokens - (approx_ph_chars // 3))
        else:
            continue

        total_expected_savings += expected_savings
        candidates.append((i, msg, tool_name, content_str, est_tokens, cache_key, cached_placeholder))

    if not candidates:
        return messages, 0, 0

    # Min-reclaim gate: Prevent thrashing prompt cache prefix on negligible savings
    if not force and min_reclaim_tokens > 0 and total_expected_savings < min_reclaim_tokens:
        logger.info(
            "[ActivePrune] Skipped to protect prompt cache prefix: expected savings %d < min_reclaim %d",
            total_expected_savings,
            min_reclaim_tokens,
        )
        return messages, 0, 0

    # Pass 2: Execute pruning
    new_messages = list(messages)
    pruned = 0
    tokens_saved = 0

    for i, msg, tool_name, content_str, est_tokens, cache_key, cached_placeholder in candidates:
        if cached_placeholder is not None:
            replacement = replace_tool_message_content(msg, cached_placeholder)
            if replacement is not None:
                new_messages[i] = replacement
                pruned += 1
                tokens_saved += est_tokens - estimate_content_tokens(cached_placeholder)
            continue

        placeholder_text: str | None = None

        if on_prune_offload is not None:
            try:
                raw_result = await on_prune_offload(
                    content=content_str,
                    tool_name=tool_name,
                    scope_id=chat_id,
                )
                result: ContextOffloadResult = normalize_context_offload_result(raw_result)
                if result.success and result.path:
                    archive_ref = build_tool_result_archive_reference(
                        tool_name=tool_name,
                        archive_path=result.path,
                        content=content_str,
                        original_tokens=est_tokens,
                        original_chars=len(content_str),
                    )
                    placeholder_text = archive_ref.render_for_model()
            except Exception:
                logger.debug("active_prune: offload failed for %s, falling back", tool_name)

        if placeholder_text is None and effective_fallback:
            placeholder_text = build_memory_truncated_placeholder(
                tool_name=tool_name,
                content=content_str,
                est_tokens=est_tokens,
                head_chars=head_chars,
                tail_chars=tail_chars,
                reason=reason,
            )

        if placeholder_text is not None:
            cache[cache_key] = placeholder_text
            replacement = replace_tool_message_content(msg, placeholder_text)
            if replacement is not None:
                new_messages[i] = replacement
                pruned += 1
                tokens_saved += est_tokens - estimate_content_tokens(placeholder_text)

    return new_messages, pruned, tokens_saved


class ActiveToolResultPruneProcessor(BaseProcessor):
    """Replace large tool results from completed steps with archive placeholders.

    Only prunes results that:
    1. Are from earlier steps (the most recent assistant+tool exchange is kept).
    2. Exceed ``threshold_tokens`` (default 2048).
    3. Are not from protected tools (``BUILTIN_PROTECTED_TOOLS``).
    4. Pass the ``min_reclaim_tokens`` gate (protects prompt cache prefix from thrashing).

    When the offload callback is unavailable or fails:
    - By default, original content is preserved (fail-safe, no data loss).
    - When ``enable_memory_fallback=True`` or ``force_prune=True`` (e.g. before compaction),
      it gracefully truncates head & tail in-memory (DSH style) to prevent context blowup.
    """

    def __init__(
        self,
        *,
        threshold_tokens: int = 2048,
        keep_recent_calls: int = 5,
        min_reclaim_tokens: int = 0,
        proactive_prune_tokens: int = 0,
        enable_memory_fallback: bool = False,
        head_chars: int = 800,
        tail_chars: int = 400,
        on_prune_offload: ContextCompressOffloadCallback | None = None,
    ) -> None:
        self._threshold_tokens = max(threshold_tokens, 256)
        self._keep_recent_calls = max(keep_recent_calls, 0)
        self._min_reclaim_tokens = max(min_reclaim_tokens, 0)
        self._proactive_prune_tokens = max(proactive_prune_tokens, 0)
        self._enable_memory_fallback = enable_memory_fallback
        self._head_chars = head_chars
        self._tail_chars = tail_chars
        self._on_prune_offload = on_prune_offload
        self._protection_config = TOOL_PROTECTION_CONFIG
        self._placeholder_cache: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "active_tool_result_prune"

    async def should_process(self, context: ProcessorContext) -> bool:
        if self._should_skip_for_cache_preservation(context):
            return False
        if not context.metadata.get("enable_active_tool_prune", True):
            return False
        if len(context.messages) < 4:
            return False

        if self._proactive_prune_tokens > 0 and not context.metadata.get("force_prune", False):
            from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

            total_tokens = estimate_messages_tokens(context.messages)
            if total_tokens < self._proactive_prune_tokens:
                return False

        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        messages = context.messages
        keep_recent = effective_keep_recent_calls(
            keep_recent_calls=self._keep_recent_calls,
            eco_mode=bool(context.metadata.get("eco_mode", False)),
        )

        effective_min_reclaim = context.metadata.get("min_reclaim_tokens", self._min_reclaim_tokens)
        try:
            min_reclaim = max(int(effective_min_reclaim), 0)
        except (ValueError, TypeError):
            min_reclaim = self._min_reclaim_tokens

        force_prune = bool(context.metadata.get("force_prune", False))
        effective_mem_fallback = bool(
            context.metadata.get(
                "enable_memory_fallback",
                self._enable_memory_fallback or force_prune,
            )
        )

        prune_reason = str(context.metadata.get("prune_reason", "active_prune"))
        new_messages, pruned, tokens_saved = await prune_tool_results_deterministic(
            messages,
            threshold_tokens=self._threshold_tokens,
            keep_recent_calls=keep_recent,
            min_reclaim_tokens=min_reclaim,
            enable_memory_fallback=effective_mem_fallback,
            head_chars=self._head_chars,
            tail_chars=self._tail_chars,
            on_prune_offload=self._on_prune_offload,
            chat_id=context.chat_id,
            placeholder_cache=self._placeholder_cache,
            force=force_prune,
            reason=prune_reason,
        )

        if pruned > 0:
            context.messages = new_messages
            context.tokens_saved += tokens_saved
            context.operations.append(f"active_prune: replaced {pruned} tool results, saved ~{tokens_saved} tokens")
            logger.info(
                "[ActivePrune] pruned=%d saved=%d",
                pruned,
                tokens_saved,
            )
            if context.chat_id:
                metrics = get_task_metrics(context.chat_id)
                if metrics is not None:
                    metrics.record_compression(
                        tokens_saved=tokens_saved,
                        compression_type="active_tool_prune",
                        details=f"active_prune: {pruned} results archived",
                        archive_count=pruned,
                    )

        return context

    @staticmethod
    def _replace_content(msg: ToolMessage, new_content: str) -> ToolMessage | None:
        """Build a replacement ToolMessage with the placeholder content."""
        return replace_tool_message_content(msg, new_content)
