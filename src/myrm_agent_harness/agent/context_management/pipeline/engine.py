"""Pipeline engine.

 Self-update reminder: once this file is updated, also update:
1. The INPUT/OUTPUT/POS comments in this file
3. agent/context_management/PROMPT_CACHE_PRACTICE.md §5 Pipeline

[INPUT]
- base::BaseProcessor, ProcessorContext (POS: processor base class and context data structure)
- infra.session_lock::acquire_context_lock (POS: Session-level lock manager. Provides per-session async locks ensuring serialized context mutations within a session while allowing cross-session parallelism. Includes automatic cleanup.)
- utils.logger_utils::get_agent_logger (POS: agent logging utility)

[OUTPUT]
- ContextPipeline: Context processing pipeline (manages processor chain execution)

[POS]
Pipeline engine. Manages processor chain execution order and flow control, executing processors sequentially in a chain-of-responsibility pattern.

"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..infra.session_lock import acquire_context_lock, get_current_chat_id
from .base import BaseProcessor, ProcessorContext

if TYPE_CHECKING:
    from ..archive_checkpoint import ArchiveSummaryService
    from ..infra.schemas import (
        CacheTtlPruneConfig,
        ContextCompressEvictionCallback,
        ContextCompressOffloadCallback,
        ContextPreCompactCallback,
        ContextSnapshotCallback,
    )
    from ..strategies.session_notes.updater import SessionNotesManager

logger = get_agent_logger(__name__)


class ContextPipeline:
    """Context processing pipeline.

    Data flows through processors sequentially; each processor independently decides
    whether to process.

    Features:
    - Chain-of-responsibility: data passes through each processor in order
    - Conditional execution: each processor self-determines whether to run
    - Extensible: supports dynamic add/remove of processors
    - Observable: logs execution status of each processor

    Usage:
        pipeline = ContextPipeline([
            FilterProcessor(),
            CompressProcessor(),
            SummarizeProcessor(),
        ])
        result = await pipeline.process(context)
    """

    def __init__(self, processors: Sequence[BaseProcessor] | None = None):
        self.processors: list[BaseProcessor] = list(processors) if processors is not None else []

    def add_processor(self, processor: BaseProcessor) -> "ContextPipeline":
        """Add a processor (supports chaining)."""
        self.processors.append(processor)
        return self

    def remove_processor(self, name: str) -> bool:
        """Remove a processor by name. Returns True if found and removed."""
        for i, p in enumerate(self.processors):
            if p.name == name:
                self.processors.pop(i)
                return True
        return False

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        """Execute the pipeline.

        Individual processor exceptions do not abort the pipeline: on failure,
        context is preserved and subsequent processors continue.
        """
        lock_chat_id = context.chat_id or get_current_chat_id()
        if lock_chat_id is None:
            return await self._process_unlocked(context)

        async with acquire_context_lock(lock_chat_id):
            return await self._process_unlocked(context)

    async def _process_unlocked(self, context: ProcessorContext) -> ProcessorContext:
        """Run processors while the caller owns any required session lock."""
        executed: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []

        for processor in self.processors:
            if await processor.should_process(context):
                try:
                    context = await processor.process(context)
                    context.operations.append(processor.name)
                    executed.append(processor.name)
                except Exception as exc:
                    logger.error("Processor %s failed: %s", processor.name, exc)
                    failed.append(processor.name)
            else:
                skipped.append(processor.name)

        parts = [f"executed: {executed}", f"skipped: {len(skipped)}"]
        if failed:
            parts.append(f"failed: {failed}")
        parts.append(f"saved: {context.tokens_saved} tokens")
        summary = " | ".join(parts)
        if failed:
            logger.warning("[Pipeline] %s", summary)
        else:
            logger.info("[Pipeline] %s", summary)
        return context


def create_default_pipeline(max_context_tokens: int | None = None) -> ContextPipeline:
    """Create the default pipeline.

    Default processor chain (in execution order):
    1. ThinkingBlockCleaner — clean thinking blocks
    2. MediaFilterProcessor — strip media for text-only models (proactive)
    3. FilterProcessor — truncate large tool results
    4. CacheTtlPruneProcessor — rule-based pruning of expired tool results (zero API cost)
    5. PreCompactProcessor — semantic memory recall before compaction (optional)
    6. CompressProcessor — compress old tool calls (dynamic thresholds)
    7. SessionNotesProcessor — zero-API compression (conditionally enabled)
    8. SummarizeProcessor — summarize history (last resort)
    9. NormalizeProcessor — content normalization (clean empty lines, newlines)
    10. ExplicitCacheProcessor — explicit cache (Claude/Qwen only, auto-detected)

    External data security isolation is handled by the tool layer (content_boundary module),
    not duplicated in the pipeline layer.
    """
    return ContextPipeline(
        build_default_processors(max_context_tokens=max_context_tokens)
    )


def build_default_processors(
    *,
    max_context_tokens: int | None = None,
    tool_result_evict_threshold: int = 5000,
    compress_min_save: int = 3000,
    compress_batch_rounds: int = 5,
    keep_recent_calls: int = 5,
    tail_budget_ratio: float = 0.20,
    on_compress_offload: "ContextCompressOffloadCallback | None" = None,
    on_compress_eviction: "ContextCompressEvictionCallback | None" = None,
    on_context_snapshot: "ContextSnapshotCallback | None" = None,
    on_pre_compact: "ContextPreCompactCallback | None" = None,
    archive_summary_service: "ArchiveSummaryService | None" = None,
    session_notes_manager: "SessionNotesManager | None" = None,
    time_decay_half_life_days: float | None = None,
    cache_ttl_prune_config: "CacheTtlPruneConfig | None" = None,
) -> list[BaseProcessor]:
    """Build the unified default processor chain.

    All entry points must share the same processor assembly order to prevent
    capability divergence between default pipeline, middleware pipeline,
    and Evolution pipeline.
    """
    from ..infra.schemas import ContextConfig
    from .processors import (
        CacheTtlPruneProcessor,
        CompressProcessor,
        ExplicitCacheProcessor,
        FilterProcessor,
        MediaFilterProcessor,
        NormalizeProcessor,
        PreCompactProcessor,
        SessionNotesProcessor,
        SummarizeProcessor,
        ThinkingBlockCleaner,
    )

    max_context = max_context_tokens or 128000
    config = (
        ContextConfig(
            max_context_tokens=max_context,
            time_decay_half_life_days=time_decay_half_life_days,
            tail_budget_ratio=tail_budget_ratio,
        )
        if time_decay_half_life_days is not None
        else ContextConfig(max_context_tokens=max_context, tail_budget_ratio=tail_budget_ratio)
    )

    compress_processor = CompressProcessor(
        max_context_tokens=max_context,
        tool_result_evict_threshold=tool_result_evict_threshold,
        compress_min_save=compress_min_save,
        compress_batch_rounds=compress_batch_rounds,
        keep_recent_calls=keep_recent_calls,
        on_compress_offload=on_compress_offload,
        on_compress_eviction=on_compress_eviction,
        on_context_snapshot=on_context_snapshot,
    )
    summarize_processor = SummarizeProcessor(config=config)
    session_notes_processor = (
        SessionNotesProcessor(
            manager=session_notes_manager,
            summarize_trigger_threshold=config.summarize_trigger_threshold,
        )
        if session_notes_manager is not None
        else None
    )

    processors: list[BaseProcessor] = [
        ThinkingBlockCleaner(),
        MediaFilterProcessor(),
        FilterProcessor(),
        CacheTtlPruneProcessor(
            config=cache_ttl_prune_config,
            max_context_tokens=max_context,
            on_prune_offload=on_compress_offload,
            archive_summary_service=archive_summary_service,
        ),
    ]

    if on_pre_compact is not None:
        processors.append(
            PreCompactProcessor(
                compress_processor=compress_processor,
                summarize_processor=summarize_processor,
                session_notes_processor=session_notes_processor,
                on_pre_compact=on_pre_compact,
            )
        )

    processors.append(compress_processor)

    if session_notes_processor is not None:
        processors.append(session_notes_processor)

    processors.extend(
        [
            summarize_processor,
            NormalizeProcessor(),
            ExplicitCacheProcessor(),
        ]
    )

    return processors
