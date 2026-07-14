"""Reasoning model timeout floor detection.

[INPUT]
- (none)

[OUTPUT]
- get_reasoning_timeout_floor(): Returns the minimum timeout floor for a model slug

[POS]
Reasoning models (OpenAI o-series, DeepSeek-R1, Nemotron, etc.) require longer
timeouts due to extended thinking phases. This module provides model-specific
timeout floors that override the default 300s when a reasoning model is detected.
Used by create_litellm_model() to automatically adjust force_timeout.
"""

from __future__ import annotations

_REASONING_TIMEOUT_FLOORS: dict[str, float] = {
    # OpenAI o-series (thinking phase does not stream data)
    "o1": 600.0,
    "o1-mini": 600.0,
    "o1-pro": 600.0,
    "o1-preview": 600.0,
    "o3": 600.0,
    "o3-pro": 600.0,
    "o3-mini": 450.0,
    "o4-mini": 450.0,
    # DeepSeek reasoning (streams thinking tokens, but long total time possible)
    "deepseek-r1": 600.0,
    "deepseek-reasoner": 600.0,
    "deepseek-v4-pro": 600.0,
    "deepseek-v4-flash": 450.0,
    # NVIDIA Nemotron
    "nemotron-3-ultra": 600.0,
    "nemotron-3-super": 600.0,
    # Qwen reasoning
    "qwq": 450.0,
    # Google Gemini thinking
    "gemini-2.5": 450.0,
    # xAI Grok reasoning
    "grok-4-fast-reasoning": 450.0,
    "grok-4.20-reasoning": 450.0,
}


_SORTED_PREFIXES: tuple[tuple[str, float], ...] = tuple(
    sorted(_REASONING_TIMEOUT_FLOORS.items(), key=lambda x: -len(x[0]))
)


def get_reasoning_timeout_floor(model: str) -> float | None:
    """Return the minimum timeout (seconds) for a reasoning model, or None.

    Uses prefix matching against the model slug (case-insensitive) to handle
    versioned model names (e.g. "o3-2025-04-16" matches "o3"). Longer prefixes
    are matched first to ensure "o3-mini" matches before "o3".

    Args:
        model: Model identifier (e.g. "openai/o3", "deepseek/deepseek-r1")

    Returns:
        Timeout floor in seconds, or None if the model is not a known reasoning model.
    """
    if not model:
        return None

    slug = model.rsplit("/", 1)[-1].lower()

    for prefix, floor in _SORTED_PREFIXES:
        if slug.startswith(prefix):
            return floor

    return None
