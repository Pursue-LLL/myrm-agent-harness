"""Selective Eviction Processor.

Executes mark-driven safe eviction of transient messages (hints, scratchpads)
prior to destructive LLM summarization or heavy tool-call compression, honoring
the Tool Pair Invariant and whitelist immunity for pinned rules.

[INPUT]
- base::BaseProcessor, ProcessorContext (POS: processor contracts)
- ...strategies.compactor.selective_eviction::evict_messages_by_marks, SelectiveEvictionStats
- ...working_memory.marks::WorkingMemoryMark, has_message_marks

[OUTPUT]
- SelectiveEvictionProcessor: pipeline processor for mark-based selective pruning

[POS]
Pipeline pre-compactor stage. Sheds transient tokens deterministically with zero LLM cost.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.agent.context_management.pipeline.base import (
    BaseProcessor,
    ProcessorContext,
)
from myrm_agent_harness.agent.context_management.strategies.compactor.selective_eviction import (
    DEFAULT_TRANSIENT_MARKS,
    evict_messages_by_marks,
)
from myrm_agent_harness.agent.context_management.working_memory.marks import (
    has_message_marks,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class SelectiveEvictionProcessor(BaseProcessor):
    """Pipeline processor performing deterministic mark-based selective pruning."""

    def __init__(
        self,
        target_marks: Sequence[str] | None = None,
        preserve_marks: Sequence[str] | None = None,
    ) -> None:
        self.target_marks: frozenset[str] = (
            frozenset(target_marks) if target_marks is not None else DEFAULT_TRANSIENT_MARKS
        )
        self.preserve_marks: frozenset[str] = (
            frozenset(preserve_marks) if preserve_marks is not None else frozenset()
        )

    @property
    def name(self) -> str:
        return "selective_eviction"

    async def should_process(self, context: ProcessorContext) -> bool:
        """Check if any message in context carries targeted marks."""
        # Prompt Cache preservation: skip during resume or HITL active sessions
        if self._should_skip_for_cache_preservation(context):
            return False

        if not context.messages:
            return False

        return any(has_message_marks(msg, *self.target_marks) for msg in context.messages)

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        """Execute selective eviction."""
        new_msgs, stats = evict_messages_by_marks(
            context.messages,
            target_marks=self.target_marks,
            preserve_marks=self.preserve_marks,
        )

        if stats.evicted_count > 0:
            context.messages = new_msgs
            context.tokens_saved += stats.tokens_saved
            op_desc = (
                f"selective_eviction: pruned {stats.evicted_count} messages "
                f"(marks={stats.evicted_marks}, saved ~{stats.tokens_saved} tokens, "
                f"protected={stats.immune_protected_count}, folded_tools={stats.tool_pairs_folded})"
            )
            context.operations.append(op_desc)
            context.metadata["selective_eviction_stats"] = {
                "evicted_count": stats.evicted_count,
                "tokens_saved": stats.tokens_saved,
                "evicted_marks": list(stats.evicted_marks),
                "immune_protected_count": stats.immune_protected_count,
                "tool_pairs_folded": stats.tool_pairs_folded,
            }

        return context
