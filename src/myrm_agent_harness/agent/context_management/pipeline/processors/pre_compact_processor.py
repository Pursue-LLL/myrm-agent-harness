"""Pre-compaction memory recall processor.

Runs before Compress / SessionNotes / Summarize when any compaction tier is about to execute.
Invokes ContextPreCompactCallback to inject a protected HumanMessage recall block.

[INPUT]
- pipeline.processors.compress_processor::CompressProcessor
- pipeline.processors.session_notes_processor::SessionNotesProcessor
- pipeline.processors.summarize_processor::SummarizeProcessor

[OUTPUT]
- PreCompactProcessor: pre-compaction recall processor

[POS]
Pipeline processor that preserves durable memory constraints before context compaction.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.infra.schemas import (
    PRE_COMPACT_INJECTION_METADATA_KEY,
    PRE_COMPACT_MESSAGE_METADATA_KEY,
    ContextPreCompactCallback,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.compress_processor import (
    CompressProcessor,
    _extract_user_goal_hint,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.session_notes_processor import (
    SessionNotesProcessor,
)
from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
    SummarizeProcessor,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)


class PreCompactProcessor(BaseProcessor):
    """Inject semantic memory recall before compaction mutates the message list."""

    def __init__(
        self,
        *,
        compress_processor: CompressProcessor,
        summarize_processor: SummarizeProcessor,
        session_notes_processor: SessionNotesProcessor | None = None,
        on_pre_compact: ContextPreCompactCallback | None = None,
    ) -> None:
        self._compress_processor = compress_processor
        self._summarize_processor = summarize_processor
        self._session_notes_processor = session_notes_processor
        self._on_pre_compact = on_pre_compact

    @property
    def name(self) -> str:
        return "pre_compact"

    async def should_process(self, context: ProcessorContext) -> bool:
        if self._on_pre_compact is None:
            return False
        if context.metadata.get(PRE_COMPACT_MESSAGE_METADATA_KEY) is not None:
            return False

        tier = await self._resolve_compaction_tier(context)
        if tier is None:
            return False

        context.metadata["pre_compact_tier"] = tier
        return True

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        if self._on_pre_compact is None:
            return context

        tier_obj = context.metadata.get("pre_compact_tier")
        tier = tier_obj if isinstance(tier_obj, str) else "compress"
        total_tokens = estimate_messages_tokens(context.messages)
        max_tokens = self._compress_processor.config.max_context_tokens or 128000
        pressure_ratio = min(total_tokens / max_tokens, 1.0) if max_tokens > 0 else 0.0
        user_goal_hint = _extract_user_goal_hint(context)

        try:
            injection = await self._on_pre_compact(
                messages=context.messages,
                chat_id=context.chat_id,
                user_id=context.user_id,
                compaction_tier=tier,
                token_pressure_ratio=pressure_ratio,
                user_goal_hint=user_goal_hint,
            )
        except Exception as exc:
            logger.warning("[PreCompact] callback failed (non-blocking): %s", exc)
            return context

        if injection is None:
            return context

        context.metadata[PRE_COMPACT_MESSAGE_METADATA_KEY] = injection.message
        context.metadata[PRE_COMPACT_INJECTION_METADATA_KEY] = injection
        logger.info(
            "[PreCompact] prepared recall inject | tier=%s recalled=%d tokens~=%d query=%.80s",
            injection.compaction_tier,
            len(injection.recalled_ids),
            injection.token_estimate,
            injection.query,
        )
        return context

    async def _resolve_compaction_tier(self, context: ProcessorContext) -> str | None:
        if context.metadata.get("compaction_debt_pending") is True:
            return "debt_pending"

        if await self._compress_processor.should_process(context):
            return "compress"

        if self._session_notes_processor is not None and await self._session_notes_processor.should_process(context):
            return "session_notes"

        if await self._summarize_processor.should_process(context):
            return "summarize"

        return None
