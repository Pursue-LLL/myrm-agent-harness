"""Thinking model max_tokens headroom adjustment.

[INPUT]
- model identifier, llm_kwargs mapping

[OUTPUT]
- ensure_thinking_headroom(): proactively raise max_tokens when a thinking
  model is detected, preventing truncation caused by thinking tokens
  consuming the output budget.
- thinking_output_floor(): return output-token floor applied to a thinking model.

[POS]
Stateless facade delegating to the unified reasoning_profile SSOT.
Raises max_tokens to a safe floor for thinking models.
"""

from __future__ import annotations

from typing import Mapping

from myrm_agent_harness.toolkits.llms.core.reasoning_profile import (
    _DEFAULT_HEADROOM_FLOOR,
    _EFFORT_HEADROOM_FLOORS,
    apply_thinking_headroom,
    extract_reasoning_effort,
    get_model_headroom_floor,
    is_thinking_model,
)

# Export legacy symbols for backwards compatibility with tests and consumers
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
    "minimax-m",
    "grok-4",
)
_EFFORT_FLOORS: dict[str, int] = _EFFORT_HEADROOM_FLOORS
_DEFAULT_FLOOR: int = _DEFAULT_HEADROOM_FLOOR


def _is_thinking_model(model: str) -> bool:
    """Check whether a model slug matches a known thinking/reasoning model."""
    return is_thinking_model(model)


def _extract_effort(llm_kwargs: Mapping[str, object] | None) -> str | None:
    """Extract reasoning effort from all possible locations in llm_kwargs."""
    return extract_reasoning_effort(llm_kwargs)


def thinking_output_floor(
    model: str,
    llm_kwargs: Mapping[str, object] | None = None,
) -> int | None:
    """Return the output-token floor applied to a thinking model, else None."""
    return get_model_headroom_floor(model, llm_kwargs)


def ensure_thinking_headroom(model: str, llm_kwargs: dict[str, object]) -> None:
    """Raise max_tokens to a safe floor for thinking models."""
    apply_thinking_headroom(model, llm_kwargs)
