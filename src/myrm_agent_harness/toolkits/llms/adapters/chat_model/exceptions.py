"""ChatLiteLLM shared exceptions and adapter constants.

[INPUT]
- (none — constants and exception types only)

[OUTPUT]
- EmptyChoicesError / EmptyStreamError: retryable empty LLM response exceptions
- StreamStallTimeoutError: stream stall detection (first-event / inter-chunk timeout)
- DEVELOPER_ROLE_PATTERN, _SYSTEM_MESSAGE_DENYLIST_HINTS, _FRAMEWORK_REQUIRED_OPENAI_PARAMS

[POS]
Shared adapter constants and exception types used by ChatLiteLLM mixins.
"""

from __future__ import annotations

import re

_SYSTEM_MESSAGE_DENYLIST_HINTS = ("minimax",)

DEVELOPER_ROLE_PATTERN = re.compile(r"^(?:gpt-(?:[5-9]|\d{2,})|codex|o[1-9]\d*)")

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
        "context_management",
        "store",
        "previous_response_id",
    }
)


class EmptyChoicesError(Exception):
    """LLM returned empty choices (retryable)."""


class EmptyStreamError(Exception):
    """LLM stream produced no chunks (retryable)."""


class StreamStallTimeoutError(TimeoutError):
    """LLM stream stalled — no data received within the configured timeout.

    Raised when the provider accepts the request (HTTP 200) but fails to deliver
    stream events within `first_event_timeout` or `inter_chunk_timeout`.
    Inherits TimeoutError so existing error_classifier `_TIMEOUT_RE` automatically
    matches it, triggering transient retry and model failover.
    """

    def __init__(self, provider: str, model: str, phase: str, elapsed_s: float) -> None:
        msg = (
            f"Stream stall timeout: no data received within {elapsed_s:.1f}s "
            f"(phase={phase}, provider={provider}, model={model})"
        )
        super().__init__(msg)
        self.provider = provider
        self.model = model
        self.phase = phase
        self.elapsed_s = elapsed_s
