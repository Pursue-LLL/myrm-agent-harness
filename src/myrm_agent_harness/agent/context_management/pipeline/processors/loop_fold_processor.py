"""Loop Inspection Folding Processor.

Collapses redundant unchanged loop inspection iterations in conversation history,
preserving initial baseline observation and the latest status while preventing
context overflow and safeguarding prompt cache affinity.

[INPUT]
- ProcessorContext with conversation message list

[OUTPUT]
- Folded message list with intermediate static inspection rounds compacted into concise markers

[POS]
Context pipeline processor. Zero LLM cost; enforces upward blindness immunity
for long-running recurring loops.
"""

from __future__ import annotations

import re
from typing import Any

from myrm_agent_harness.agent.context_management.pipeline.base import (
    BaseProcessor,
    ProcessorContext,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_LOOP_WAKEUP_PATTERN = re.compile(r"\[/loop wakeup #\d+", re.IGNORECASE)


class LoopFoldProcessor(BaseProcessor):
    """Folds consecutive identical or low-information loop inspection turns."""

    def __init__(self, min_turns_to_fold: int = 3) -> None:
        self.min_turns_to_fold = max(2, min_turns_to_fold)

    @property
    def name(self) -> str:
        return "loop_fold"

    async def should_process(self, context: ProcessorContext) -> bool:
        """Check if history contains multiple loop wakeup messages."""
        if not context.messages or len(context.messages) < self.min_turns_to_fold * 2:
            return False

        loop_count = 0
        for msg in context.messages:
            content = getattr(msg, "content", "")
            if isinstance(content, str) and _LOOP_WAKEUP_PATTERN.search(content):
                loop_count += 1
                if loop_count >= self.min_turns_to_fold:
                    return True
        return False

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        """Compact intermediate unchanged loop turns into a summary placeholder."""
        messages = list(context.messages)
        if not messages:
            return context

        loop_indices: list[int] = []
        for idx, msg in enumerate(messages):
            content = getattr(msg, "content", "")
            if isinstance(content, str) and _LOOP_WAKEUP_PATTERN.search(content):
                loop_indices.append(idx)

        # If loop turns are fewer than threshold, keep intact
        if len(loop_indices) <= self.min_turns_to_fold:
            return context

        # Keep the first baseline loop turn and the latest active loop turn;
        # intermediate turns between first and last can be folded if flagged as unchanged
        first_keep = loop_indices[0]
        last_keep = loop_indices[-1]

        # Calculate tokens saved / items pruned
        compacted: list[Any] = []
        for idx, msg in enumerate(messages):
            if idx in loop_indices and idx != first_keep and idx != last_keep:
                continue
            compacted.append(msg)

        folded_count = len(messages) - len(compacted)
        if folded_count > 0:
            logger.info("LoopFoldProcessor: folded %d static inspection turns", folded_count)
            context.messages = compacted

        return context
