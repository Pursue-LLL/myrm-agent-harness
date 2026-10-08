"""Injects active ephemeral session deltas at the tail of the final HumanMessage.

[INPUT]
- toolkits.memory.ephemeral_delta.models::EphemeralDeltaItem (POS: Types and models for ephemeral delta.)
- Third-party: langchain_core

[OUTPUT]
- HumanTailDeltaInjector: Injects active ephemeral session deltas at the tail of the final HumanMessage.

[POS]
Injects active ephemeral session deltas at the tail of the final HumanMessage.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Sequence
from typing import cast

from langchain_core.messages import BaseMessage, HumanMessage

from myrm_agent_harness.toolkits.memory.ephemeral_delta.models import (
    EphemeralDeltaItem,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_DELTA_CHARS = 1500


class HumanTailDeltaInjector:
    """Injects active ephemeral session deltas at the tail of the final HumanMessage.

    Prompt Cache Invariant:
    1. Preceding SystemPrompt and prior history messages remain 100% untouched.
    2. Zero cache invalidation occurs on the frozen prefix.
    3. The transformer attention recency bias ensures current-turn adherence.
    """

    def __init__(self, max_delta_chars: int = _DEFAULT_MAX_DELTA_CHARS) -> None:
        self.max_delta_chars = max_delta_chars

    def format_deltas_block(
        self,
        deltas: Sequence[EphemeralDeltaItem],
    ) -> str:
        """Format deltas into a compact, sanitized XML tag block."""
        if not deltas:
            return ""

        lines: list[str] = [
            "<ephemeral_session_deltas>",
            "  <!-- Active session corrections & transient overrides. Precedence: overrides baseline facts. -->",
        ]

        total_chars = 0
        for item in deltas:
            escaped_key = html.escape(item.target_key)
            escaped_action = html.escape(item.action.value)
            escaped_id = html.escape(item.delta_id)
            escaped_content = html.escape(item.content.strip())

            delta_line = (
                f'  <delta id="{escaped_id}" key="{escaped_key}" '
                f'action="{escaped_action}">{escaped_content}</delta>'
            )

            # Enforce budget guard
            if total_chars + len(delta_line) > self.max_delta_chars:
                lines.append(
                    '  <!-- Remaining deltas truncated due to budget constraints -->'
                )
                break

            lines.append(delta_line)
            total_chars += len(delta_line)

        lines.append("</ephemeral_session_deltas>")
        return "\n".join(lines)

    def inject_deltas(
        self,
        messages: Sequence[BaseMessage],
        deltas: Sequence[EphemeralDeltaItem],
    ) -> list[BaseMessage]:
        """Attach active deltas to the tail of the last HumanMessage in the sequence.

        If no active deltas or no HumanMessage exists, returns the original sequence untouched.
        """
        if not deltas or not messages:
            return list(messages)

        formatted_block = self.format_deltas_block(deltas)
        if not formatted_block:
            return list(messages)

        # Locate the index of the final HumanMessage
        target_idx = -1
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                target_idx = i
                break

        if target_idx == -1:
            logger.debug(
                "No HumanMessage found in request messages; skipping tail injection"
            )
            return list(messages)

        out_messages = list(messages)
        original_human = cast(HumanMessage, out_messages[target_idx])

        # Preserve multimodal or plain string structures
        if isinstance(original_human.content, str):
            new_content = (
                f"{original_human.content}\n\n{formatted_block}"
                if original_human.content
                else formatted_block
            )
            updated_msg = HumanMessage(
                content=new_content,
                additional_kwargs=dict(original_human.additional_kwargs),
                id=original_human.id,
                name=original_human.name,
            )
            out_messages[target_idx] = updated_msg
        elif isinstance(original_human.content, list):
            # Append as a text block at the end of the content array
            new_content_list: list[dict[str, str]] = []
            for block in original_human.content:
                if isinstance(block, dict):
                    new_content_list.append(
                        {k: str(v) for k, v in block.items()}
                    )
            new_content_list.append(
                {"type": "text", "text": f"\n\n{formatted_block}"}
            )
            updated_msg = HumanMessage(
                content=cast(list[dict[str, str]], new_content_list),
                additional_kwargs=dict(original_human.additional_kwargs),
                id=original_human.id,
                name=original_human.name,
            )
            out_messages[target_idx] = updated_msg

        return out_messages
