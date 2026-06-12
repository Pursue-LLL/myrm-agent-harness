"""Ephemeral max-output-tokens override for truncation recovery.

[INPUT]
- contextvars::ContextVar (POS: per-request LLM output budget override)

[OUTPUT]
- ephemeral_max_output_tokens: ContextVar[int | None]
- get_ephemeral_max_output_tokens / set_ephemeral_max_output_tokens / reset_ephemeral_max_output_tokens
- MAX_EPHEMERAL_OUTPUT_TOKENS: int cap constant

[POS]
ChatLiteLLM reads this once per request; stream recovery sets it before retrying truncated responses.
"""

from __future__ import annotations

from contextvars import ContextVar

MAX_EPHEMERAL_OUTPUT_TOKENS = 32768

ephemeral_max_output_tokens: ContextVar[int | None] = ContextVar(
    "ephemeral_max_output_tokens",
    default=None,
)


def get_ephemeral_max_output_tokens() -> int | None:
    """Read the ephemeral override (returns None when unset)."""
    return ephemeral_max_output_tokens.get()


def set_ephemeral_max_output_tokens(value: int) -> None:
    """Set the ephemeral override (capped at MAX_EPHEMERAL_OUTPUT_TOKENS)."""
    ephemeral_max_output_tokens.set(min(value, MAX_EPHEMERAL_OUTPUT_TOKENS))


def reset_ephemeral_max_output_tokens() -> None:
    """Clear the ephemeral override so subsequent calls use the default."""
    ephemeral_max_output_tokens.set(None)


__all__ = [
    "MAX_EPHEMERAL_OUTPUT_TOKENS",
    "ephemeral_max_output_tokens",
    "get_ephemeral_max_output_tokens",
    "reset_ephemeral_max_output_tokens",
    "set_ephemeral_max_output_tokens",
]
