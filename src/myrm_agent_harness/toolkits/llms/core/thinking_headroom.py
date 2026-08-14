"""Thinking model max_tokens headroom adjustment.

[INPUT]
- (none, stateless utility)

[OUTPUT]
- ensure_thinking_headroom(): proactively raise max_tokens when a thinking
  model is detected, preventing truncation caused by thinking tokens
  consuming the output budget.

[POS]
All major reasoning model providers (Anthropic, DeepSeek, OpenAI, Google)
count thinking/reasoning tokens against max_tokens.  When users set a modest
max_tokens (e.g. 4096 or 8192), the thinking phase can exhaust the budget
before the response even starts — causing a guaranteed truncation that wastes
an entire API round-trip via stream recovery.

This module bridges the gap at LLM-creation time: it detects thinking-capable
models, reads the requested reasoning effort (if any), and raises max_tokens
to a safe floor so both thinking and response fit within the budget.  When no
effort is explicitly set, a conservative default floor is applied because all
thinking models default to thinking-on.  The existing post-hoc
`_boost_output_tokens` recovery remains as a fallback for edge cases.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_THINKING_MODEL_PREFIXES: tuple[str, ...] = (
    "claude-opus",
    "claude-sonnet-4",
    "claude-fable",
    "claude-mythos",
    "claude-4",
    "o1",
    "o3",
    "o4",
    "deepseek-r1",
    "deepseek-reasoner",
    "deepseek-v4",
    "gemini-2.5",
    "gemini-3",
    "nemotron",
    "qwq",
    "grok-4",
)

_EFFORT_FLOORS: dict[str, int] = {
    "low": 8192,
    "medium": 16384,
    "high": 32768,
    "xhigh": 65536,
    "max": 65536,
}

_DEFAULT_FLOOR = 16384


def _is_thinking_model(model: str) -> bool:
    """Check whether a model slug matches a known thinking/reasoning model."""
    if not model:
        return False
    slug = model.rsplit("/", 1)[-1].lower()
    return any(slug.startswith(prefix) for prefix in _THINKING_MODEL_PREFIXES)


def _extract_effort(llm_kwargs: dict[str, Any]) -> str | None:
    """Extract reasoning effort from all possible locations in llm_kwargs.

    Effort may appear in (checked in order):
    1. Top-level ``reasoning_effort``
    2. ``extra_body.reasoning_effort``
    3. ``extra_body.reasoning.effort`` (after OpenRouter rewrite)
    """
    effort = llm_kwargs.get("reasoning_effort")
    if effort is not None:
        return str(effort).lower()

    extra_body = llm_kwargs.get("extra_body")
    if not isinstance(extra_body, dict):
        return None

    effort = extra_body.get("reasoning_effort")
    if effort is not None:
        return str(effort).lower()

    reasoning = extra_body.get("reasoning")
    if isinstance(reasoning, dict):
        effort = reasoning.get("effort")
        if effort is not None:
            return str(effort).lower()

    return None


def ensure_thinking_headroom(model: str, llm_kwargs: dict[str, Any]) -> None:
    """Raise max_tokens to a safe floor for thinking models.

    Thinking-capable models (Claude 4.6+, DeepSeek R1, OpenAI o-series,
    Gemini 2.5+) count thinking tokens against max_tokens.  When max_tokens
    is too small, the thinking phase exhausts the budget and the response is
    truncated — wasting an API round-trip via stream recovery.

    This function applies an effort-based floor when reasoning_effort is
    explicitly set, or a conservative default floor when the model is a
    known thinking model but no effort is provided (all thinking models
    default to thinking-on, so a small max_tokens will still truncate).

    For non-thinking models this is a no-op.  Uses ``max()`` semantics to
    only raise — never lower — the user's value.

    Args:
        model: Full LiteLLM model identifier (e.g. ``anthropic/claude-opus-5``).
        llm_kwargs: Mutable LLM parameter dict (modified in place).
    """
    if not _is_thinking_model(model):
        return

    effort = _extract_effort(llm_kwargs)
    floor = _EFFORT_FLOORS.get(effort, _DEFAULT_FLOOR) if effort else _DEFAULT_FLOOR
    current = llm_kwargs.get("max_tokens")

    if not isinstance(current, int) or current <= 0:
        llm_kwargs["max_tokens"] = floor
        logger.info(
            "Thinking headroom: set max_tokens=%d for %s (effort=%s, was unset)",
            floor,
            model,
            effort or "default",
        )
        return

    if current < floor:
        llm_kwargs["max_tokens"] = floor
        logger.info(
            "Thinking headroom: raised max_tokens %d → %d for %s (effort=%s)",
            current,
            floor,
            model,
            effort or "default",
        )
