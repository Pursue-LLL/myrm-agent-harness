"""Reasoning model timeout floor detection.

[INPUT]
- model identifier, optional llm_kwargs mapping

[OUTPUT]
- get_reasoning_timeout_floor(): Returns the minimum timeout floor for a model slug

[POS]
Stateless facade delegating to the unified reasoning_profile SSOT.
Reasoning models require longer timeouts due to extended thinking phases.
This module provides model-specific timeout floors that override the default 300s.
"""

from __future__ import annotations

from typing import Mapping

from myrm_agent_harness.toolkits.llms.core.reasoning_profile import (
    get_model_timeout_floor,
)


def get_reasoning_timeout_floor(
    model: str,
    llm_kwargs: Mapping[str, object] | None = None,
) -> float | None:
    """Return the minimum timeout (seconds) for a reasoning model, or None."""
    return get_model_timeout_floor(model, llm_kwargs)
