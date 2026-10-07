"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/noise_filter.py
[INPUT]: ConversationTurn sequences containing raw tool outputs, JSON blocks, or XML tags.
[OUTPUT]: ToolStrippedMessage list and clean transcript string stripped of non-natural language noise.

Reference: Anthropic Commerce Agents (commerce_common/memory.py).
Explicitly strips tool inputs, tool execution outputs, and non-natural language payloads
so that product catalog text, web scraping snippets, and execution logs never leak into user profile memory.
"""

import re
from collections.abc import Sequence

from .types import ConversationTurn, ToolStrippedMessage


class ToolNoiseFilter:
    """Filters conversation history to yield pure human-assistant conversational dialogue."""

    # Matches internal tool blocks or JSON dumps often embedded in raw assistant turns
    _TOOL_BLOCK_PATTERN = re.compile(
        r"```(?:tool_code|tool_output|json)?\s*[\{\[].*?[\}\]]\s*```",
        re.DOTALL | re.IGNORECASE,
    )
    _INVOCATION_TAG_PATTERN = re.compile(
        r"<function_calls?>.*?</function_calls?>|<tool_results?>.*?</tool_results?>",
        re.DOTALL | re.IGNORECASE,
    )

    def __init__(self, strip_code_blocks: bool = False) -> None:
        self.strip_code_blocks = strip_code_blocks

    def strip_turn(self, turn: ConversationTurn) -> ToolStrippedMessage | None:
        """Strip a single turn. Returns None if the turn is entirely tool execution noise."""
        # 1. Tool execution outputs are completely discarded
        if turn.role == "tool" or turn.tool_call_id is not None:
            return None

        # 2. System prompts are typically omitted from episodic preference extraction
        if turn.role == "system":
            return None

        # 3. Clean assistant or user content
        raw_text = turn.content or ""
        original_length = len(raw_text)

        # Remove function call XML or JSON artifacts if present
        clean_text = self._INVOCATION_TAG_PATTERN.sub("", raw_text)
        clean_text = self._TOOL_BLOCK_PATTERN.sub("", clean_text)

        if self.strip_code_blocks:
            clean_text = re.sub(r"```[\s\S]*?```", "", clean_text)

        clean_text = clean_text.strip()
        if not clean_text:
            return None

        stripped_chars = max(0, original_length - len(clean_text))
        # Approximate 4 characters per token
        tokens_saved = stripped_chars // 4

        return ToolStrippedMessage(
            role=turn.role,  # type: ignore[arg-type]
            clean_text=clean_text,
            stripped_tokens_est=tokens_saved,
        )

    def process_dialogue(
        self, turns: Sequence[ConversationTurn]
    ) -> tuple[list[ToolStrippedMessage], int]:
        """Strip an entire conversation sequence, returning clean turns and total tokens saved."""
        cleaned_messages: list[ToolStrippedMessage] = []
        total_tokens_omitted = 0

        for turn in turns:
            if turn.role == "tool" or turn.tool_call_id is not None:
                # Count discarded tool result tokens
                total_tokens_omitted += len(turn.content or "") // 4
                continue

            stripped = self.strip_turn(turn)
            if stripped:
                cleaned_messages.append(stripped)
                total_tokens_omitted += stripped.stripped_tokens_est

        return cleaned_messages, total_tokens_omitted

    def render_clean_transcript(self, turns: Sequence[ConversationTurn]) -> str:
        """Render pure natural language dialogue formatted for LLM memory extraction prompts."""
        cleaned_messages, _ = self.process_dialogue(turns)
        lines: list[str] = []
        for msg in cleaned_messages:
            speaker = "User" if msg.role == "user" else "Assistant"
            lines.append(f"{speaker}: {msg.clean_text}")
        return "\n\n".join(lines)
