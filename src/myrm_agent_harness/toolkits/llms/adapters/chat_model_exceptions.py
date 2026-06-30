"""ChatLiteLLM shared exceptions and adapter constants."""

from __future__ import annotations

import re

_SYSTEM_MESSAGE_DENYLIST_HINTS = ("minimax",)

_DEVELOPER_ROLE_PATTERN = re.compile(r"^(?:gpt-(?:[5-9]|\d{2,})|codex|o[1-9]\d*)")

# Parameters the framework may inject that must never be silently dropped
# by LiteLLM's provider capability whitelist (see `litellm.drop_params`).
_FRAMEWORK_REQUIRED_OPENAI_PARAMS: frozenset[str] = frozenset(
    {
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "stream",
        "stream_options",
    }
)


class EmptyChoicesError(Exception):
    """LLM returned empty choices (retryable)."""


class EmptyStreamError(Exception):
    """LLM stream produced no chunks (retryable)."""
