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

from langchain_core.messages import ToolMessage

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


class ActiveToolResultPruneProcessor(BaseProcessor):
    """Replace large tool results from completed steps with archive placeholders.

    Only prunes results that:
    1. Are from earlier steps (the most recent assistant+tool exchange is kept).
    2. Exceed ``threshold_tokens`` (default 2048).
    3. Are not from protected tools (``BUILTIN_PROTECTED_TOOLS``).

    When the offload callback is unavailable or fails, the original content is
    preserved (fail-safe, no data loss).
    """

    def __init__(
        self,
        *,
        threshold_tokens: int = 2048,
        keep_recent_calls: int = 5,
        on_prune_offload: ContextCompressOffloadCallback | None = None,
    ) -> None:
        self._threshold_tokens = max(threshold_tokens, 256)
        self._keep_recent_calls = max(keep_recent_calls, 0)
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
        return len(context.messages) >= 4

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        messages = context.messages
        keep_recent = effective_keep_recent_calls(
            keep_recent_calls=self._keep_recent_calls,
            eco_mode=bool(context.metadata.get("eco_mode", False)),
        )
        cutoff = find_keep_recent_prune_cutoff(messages, keep_recent)
        if cutoff <= 0:
            return context

        pruned = 0
        tokens_saved = 0
        archive_failures = 0

        for i in range(cutoff):
            msg = messages[i]
            if not isinstance(msg, ToolMessage):
                continue
            tool_name = msg.name or "unknown"
            if self._protection_config.is_active_prune_never(tool_name):
                continue

            content_str = _content_text(msg.content)
            if content_str is None:
                continue
            est_tokens = estimate_content_tokens(content_str)
            if est_tokens <= self._threshold_tokens:
                continue

            content_sha = hashlib.sha256(content_str.encode("utf-8")).hexdigest()
            cache_key = f"{msg.tool_call_id}:{content_sha}"

            cached_placeholder = self._placeholder_cache.get(cache_key)
            if cached_placeholder is not None:
                replacement = self._replace_content(msg, cached_placeholder)
                if replacement is not None:
                    messages[i] = replacement
                    pruned += 1
                    tokens_saved += est_tokens - estimate_content_tokens(cached_placeholder)
                continue

            if self._on_prune_offload is None:
                continue

            try:
                raw_result = await self._on_prune_offload(
                    content=content_str,
                    tool_name=tool_name,
                    scope_id=context.chat_id,
                )
                result: ContextOffloadResult = normalize_context_offload_result(raw_result)
            except Exception:
                logger.debug("active_prune: offload failed for %s, keeping original", tool_name)
                archive_failures += 1
                continue

            if not result.success or not result.path:
                archive_failures += 1
                continue

            archive_ref = build_tool_result_archive_reference(
                tool_name=tool_name,
                archive_path=result.path,
                content=content_str,
                original_tokens=est_tokens,
                original_chars=len(content_str),
            )
            placeholder_text = archive_ref.render_for_model()
            self._placeholder_cache[cache_key] = placeholder_text

            replacement = self._replace_content(msg, placeholder_text)
            if replacement is not None:
                messages[i] = replacement
                pruned += 1
                tokens_saved += est_tokens - estimate_content_tokens(placeholder_text)

        if pruned > 0:
            context.tokens_saved += tokens_saved
            context.operations.append(
                f"active_prune: replaced {pruned} tool results, saved ~{tokens_saved} tokens"
            )
            logger.info(
                "[ActivePrune] pruned=%d saved=%d failures=%d",
                pruned,
                tokens_saved,
                archive_failures,
            )
            if context.chat_id:
                metrics = get_task_metrics(context.chat_id)
                if metrics is not None:
                    metrics.record_compression(
                        tokens_saved=tokens_saved,
                        compression_type="active_tool_prune",
                        details=f"active_prune: {pruned} results archived, {archive_failures} failures",
                        archive_count=pruned,
                        offload_failed_count=archive_failures,
                    )

        return context

    @staticmethod
    def _replace_content(msg: ToolMessage, new_content: str) -> ToolMessage | None:
        """Build a replacement ToolMessage with the placeholder content."""
        try:
            if hasattr(msg, "model_copy"):
                return msg.model_copy(update={"content": new_content})
            return msg.copy(update={"content": new_content})
        except Exception:
            logger.debug("active_prune: failed to copy ToolMessage")
            return None
