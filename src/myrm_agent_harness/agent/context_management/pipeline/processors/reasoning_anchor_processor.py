"""Reasoning Anchor Pipeline Processor.

Extracts decision anchors from thinking streams before ThinkingBlockCleaner
strips them, and injects preserved decision anchors into the context window
without disrupting Prompt Prefix Cache.

[INPUT]
- pipeline.base::BaseProcessor, ProcessorContext (POS: Pipeline processor base class)
- strategies.reasoning.anchor_extractor::extract_raw_reasoning, extract_reasoning_anchors (POS: Extraction logic)
- strategies.reasoning.anchor_ledger::get_session_anchor_ledger (POS: Session anchor ledger)
- utils.logger_utils::get_agent_logger (POS: Agent logger)

[OUTPUT]
- ReasoningAnchorProcessor: Pipeline processor for reasoning preservation

[POS]
Positioned at the front of the default pipeline, immediately before ThinkingBlockCleaner.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ...strategies.reasoning.anchor_extractor import extract_raw_reasoning, extract_reasoning_anchors
from ...strategies.reasoning.anchor_ledger import get_session_anchor_ledger
from ..base import BaseProcessor, ProcessorContext

logger = get_agent_logger(__name__)

_ANCHOR_BLOCK_PREFIX = "[PRESERVED REASONING ANCHORS & CONSTRAINTS]"
_ANCHOR_BLOCK_REGEX = re.compile(
    r"\n\n\[PRESERVED REASONING ANCHORS & CONSTRAINTS\].*?(?=\n\n|\Z)",
    re.DOTALL,
)


class ReasoningAnchorProcessor(BaseProcessor):
    """Reasoning Anchor Processor.

    1. Scans messages for reasoning content and extracts core decision anchors
       into the session's immutable ledger before ThinkingBlockCleaner strips raw thoughts.
    2. Injects compact anchor constraints into the latest HumanMessage, preserving
       Prompt Prefix Cache stability across multiple execution steps.
    """

    def __init__(self, *, max_anchors: int = 10) -> None:
        self._max_anchors = max_anchors

    @property
    def name(self) -> str:
        return "ReasoningAnchorProcessor"

    async def should_process(self, context: ProcessorContext) -> bool:
        """Process whenever messages are present to ensure anchors are tracked and injected."""
        return bool(context.messages)

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        session_id = context.chat_id or "default_session"
        ledger = get_session_anchor_ledger(session_id, max_anchors=self._max_anchors)

        # Step 1: Scan AIMessages to extract new decision anchors before stripping
        extracted_count = 0
        for idx, msg in enumerate(context.messages):
            if isinstance(msg, AIMessage):
                raw_reasoning = extract_raw_reasoning(msg)
                if raw_reasoning:
                    anchors = extract_reasoning_anchors(raw_reasoning, turn_index=idx)
                    if anchors:
                        ledger.record_anchors(anchors)
                        extracted_count += len(anchors)

        active_anchors = ledger.get_anchors()
        context.metadata["active_reasoning_anchors"] = [
            {
                "id": a.anchor_id,
                "turn": a.turn_index,
                "category": a.category,
                "content": a.content,
            }
            for a in active_anchors
        ]

        if not active_anchors:
            return context

        # Step 2: Inject compact anchor block into the last HumanMessage
        # Finding the last HumanMessage ensures we do not mutate earlier message prefixes
        last_human_idx = -1
        for i in range(len(context.messages) - 1, -1, -1):
            if isinstance(context.messages[i], HumanMessage):
                last_human_idx = i
                break

        if last_human_idx != -1:
            human_msg = context.messages[last_human_idx]
            raw_content = human_msg.content
            rendered_block = ledger.render_anchors_context()
            if isinstance(raw_content, str):
                # Remove any existing anchor block to prevent repeated stacking
                cleaned_content = _ANCHOR_BLOCK_REGEX.sub("", raw_content).rstrip()
                updated_content = f"{cleaned_content}\n\n{rendered_block}"
                human_msg.content = updated_content
            elif isinstance(raw_content, list):
                # Multimodal content block list: locate or append text block
                cleaned_list: list[object] = []
                for item in raw_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        t_text = str(item.get("text", ""))
                        cleaned_t = _ANCHOR_BLOCK_REGEX.sub("", t_text).rstrip()
                        if cleaned_t:
                            cleaned_list.append({"type": "text", "text": cleaned_t})
                    else:
                        cleaned_list.append(item)
                cleaned_list.append({"type": "text", "text": rendered_block})
                human_msg.content = cleaned_list  # type: ignore[assignment]

        if extracted_count > 0:
            logger.info(
                "[ReasoningAnchor] Extracted %d new anchors, active total=%d (session=%s)",
                extracted_count,
                len(active_anchors),
                session_id,
            )

        return context
