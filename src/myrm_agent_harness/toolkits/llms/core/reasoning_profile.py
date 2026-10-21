"""Reasoning model single source of truth (SSOT) profile and intent contract.

[INPUT]
- model identifier (e.g. "minimax/MiniMax-M3.1-Flash-Preview", "openai/o3")
- optional llm_kwargs / request configuration mapping
- utils.model_utils::clamp_budget_to_model_ceiling (POS: keeps a raised budget within the model's known output ceiling)

[OUTPUT]
- get_model_timeout_floor(): Minimum watchdog request/stall timeout (seconds)
- get_model_headroom_floor(): Minimum token headroom budget for reasoning output
- is_thinking_model(): Whether a model qualifies as reasoning/thinking
- apply_thinking_headroom(): In-place proactive adjustment of max_tokens
- extract_reasoning_effort(): Extracted caller reasoning intensity level

[POS]
LLM Core Single Source of Truth for reasoning model capabilities, timeouts,
and headroom budgets. Eliminates fragmented dictionaries across modules by
unifying model metadata, three-level intent resolution (L1 explicit caller
intent, L2 explicit driver/config toggle, L3 authoritative catalog fallback),
and safe token/timeout bounding.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

from myrm_agent_harness.toolkits.llms.utils.model_utils import clamp_budget_to_model_ceiling

logger = logging.getLogger(__name__)

# Effort-based headroom floors (output tokens guaranteed for thinking + completion)
_EFFORT_HEADROOM_FLOORS: dict[str, int] = {
    "low": 8192,
    "medium": 16384,
    "high": 32768,
    "xhigh": 65536,
    "max": 65536,
}
_DEFAULT_HEADROOM_FLOOR: int = 16384

# Default timeouts for reasoning models (seconds)
_DEFAULT_REASONING_TIMEOUT_FLOOR: float = 450.0
_HEAVY_REASONING_TIMEOUT_FLOOR: float = 600.0

# Normalized effort values
_DISABLED_EFFORT_VALUES: frozenset[str] = frozenset({"off", "none", "disabled", "false", "0"})
_HEAVY_EFFORT_VALUES: frozenset[str] = frozenset({"high", "max", "xhigh", "ultra"})

# Authoritative catalog of known reasoning models and their baseline timeout floors (seconds)
# Ordered by specificity when matching prefixes.
_CATALOG_TIMEOUT_FLOORS: dict[str, float] = {
    # OpenAI o-series & next-gen reasoning
    "o1": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "o1-mini": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "o1-pro": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "o1-preview": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "o3": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "o3-pro": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "o3-mini": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "o4-mini": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "o4": _HEAVY_REASONING_TIMEOUT_FLOOR,
    # DeepSeek reasoning
    "deepseek-r1": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "deepseek-reasoner": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "deepseek-v4-pro": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "deepseek-v4-flash": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # MiniMax reasoning (M2, M3, M3.1)
    "minimax-m": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # NVIDIA Nemotron
    "nemotron-3-ultra": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "nemotron-3-super": _HEAVY_REASONING_TIMEOUT_FLOOR,
    "nemotron": _HEAVY_REASONING_TIMEOUT_FLOOR,
    # Qwen reasoning
    "qwq": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "qvq": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # Google Gemini thinking
    "gemini-2.5": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "gemini-3": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # Anthropic extended thinking (Opus series default-on)
    "claude-opus-4": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "claude-opus": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # xAI Grok reasoning
    "grok-4-fast-reasoning": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "grok-4.20-reasoning": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "grok-4": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # Moonshot / Kimi reasoning
    "kimi-k2": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # StepFun reasoning
    "step-r1": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    "step-3": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # Zhipu reasoning
    "glm-z1": _DEFAULT_REASONING_TIMEOUT_FLOOR,
    # Baichuan reasoning
    "baichuan-m": _DEFAULT_REASONING_TIMEOUT_FLOOR,
}

# Prefixes sorted longest first for prefix matching
_SORTED_TIMEOUT_PREFIXES: tuple[tuple[str, float], ...] = tuple(
    sorted(_CATALOG_TIMEOUT_FLOORS.items(), key=lambda item: -len(item[0]))
)

# Additional prefixes that support thinking headroom (e.g. models where thinking
# is supported when enabled or where headroom prevents token exhaustion)
_EXTENDED_HEADROOM_PREFIXES: tuple[str, ...] = (
    "claude-sonnet-4",
    "claude-fable",
    "claude-mythos",
    "claude-4",
)

_ALL_HEADROOM_PREFIXES: tuple[str, ...] = tuple(
    set(list(_CATALOG_TIMEOUT_FLOORS.keys()) + list(_EXTENDED_HEADROOM_PREFIXES))
)


def _normalize_slug(model: str) -> str:
    """Normalize model identifier by stripping provider prefix and lowering case."""
    if not model:
        return ""
    return model.rsplit("/", 1)[-1].lower()


def extract_reasoning_effort(llm_kwargs: Mapping[str, object] | None) -> str | None:
    """Extract reasoning effort from all possible locations in llm_kwargs.

    Checks in order:
    1. Top-level ``reasoning_effort``
    2. ``extra_body.reasoning_effort``
    3. ``extra_body.reasoning.effort`` (OpenRouter format)
    """
    if not llm_kwargs:
        return None

    effort = llm_kwargs.get("reasoning_effort")
    if effort is not None:
        return str(effort).lower()

    extra_body = llm_kwargs.get("extra_body")
    if not isinstance(extra_body, Mapping):
        return None

    effort = extra_body.get("reasoning_effort")
    if effort is not None:
        return str(effort).lower()

    reasoning = extra_body.get("reasoning")
    if isinstance(reasoning, Mapping):
        effort = reasoning.get("effort")
        if effort is not None:
            return str(effort).lower()

    return None


def is_reasoning_explicitly_disabled(llm_kwargs: Mapping[str, object] | None) -> bool:
    """Return True if caller explicitly turned off reasoning."""
    if not llm_kwargs:
        return False

    if llm_kwargs.get("supports_reasoning") is False:
        return True

    effort = extract_reasoning_effort(llm_kwargs)
    if effort in _DISABLED_EFFORT_VALUES:
        return True

    extra_body = llm_kwargs.get("extra_body")
    if isinstance(extra_body, Mapping):
        thinking = extra_body.get("thinking")
        if thinking is False:
            return True
        if isinstance(thinking, Mapping) and thinking.get("type") == "disabled":
            return True

    return False


def is_reasoning_explicitly_enabled(llm_kwargs: Mapping[str, object] | None) -> bool:
    """Return True if caller explicitly activated reasoning."""
    if not llm_kwargs:
        return False

    if llm_kwargs.get("supports_reasoning") is True:
        return True

    effort = extract_reasoning_effort(llm_kwargs)
    if effort is not None and effort not in _DISABLED_EFFORT_VALUES:
        return True

    extra_body = llm_kwargs.get("extra_body")
    if isinstance(extra_body, Mapping):
        thinking = extra_body.get("thinking")
        if thinking is True:
            return True
        if isinstance(thinking, Mapping) and thinking.get("type") == "enabled":
            return True

    return False


def get_model_timeout_floor(
    model: str,
    llm_kwargs: Mapping[str, object] | None = None,
) -> float | None:
    """Return the minimum timeout (seconds) for a reasoning model, or None.

    Three-tier decision ladder:
    1. L1 Intent: Explicitly disabled returns None; explicitly enabled returns
       matching catalog floor, or standard reasoning floor for custom models.
    2. L2 Driver/Config: Explicit `supports_reasoning=True` grants floor.
    3. L3 Catalog Fallback: Prefix matching against authoritative catalog.
    """
    if not model:
        return None

    if is_reasoning_explicitly_disabled(llm_kwargs):
        return None

    slug = _normalize_slug(model)

    # Check catalog first
    matched_catalog_floor: float | None = None
    for prefix, floor in _SORTED_TIMEOUT_PREFIXES:
        if slug.startswith(prefix):
            matched_catalog_floor = floor
            break

    if matched_catalog_floor is not None:
        return matched_catalog_floor

    # L2 Driver/Config: Explicit supports_reasoning=True grants floor for custom/unlisted models
    if llm_kwargs and llm_kwargs.get("supports_reasoning") is True:
        effort = extract_reasoning_effort(llm_kwargs)
        if effort in _HEAVY_EFFORT_VALUES:
            return _HEAVY_REASONING_TIMEOUT_FLOOR
        return _DEFAULT_REASONING_TIMEOUT_FLOOR

    return None


def is_thinking_model(
    model: str,
    llm_kwargs: Mapping[str, object] | None = None,
) -> bool:
    """Check whether a model qualifies as a thinking/reasoning model."""
    if not model:
        return False

    if is_reasoning_explicitly_disabled(llm_kwargs):
        return False

    if is_reasoning_explicitly_enabled(llm_kwargs):
        return True

    slug = _normalize_slug(model)
    return any(slug.startswith(prefix) for prefix in _ALL_HEADROOM_PREFIXES)


def get_model_headroom_floor(
    model: str,
    llm_kwargs: Mapping[str, object] | None = None,
) -> int | None:
    """Return the output-token headroom floor applied to a thinking model, or None."""
    if not is_thinking_model(model, llm_kwargs):
        return None

    effort = extract_reasoning_effort(llm_kwargs)
    if effort and effort in _EFFORT_HEADROOM_FLOORS:
        return _EFFORT_HEADROOM_FLOORS[effort]

    return _DEFAULT_HEADROOM_FLOOR


def apply_thinking_headroom(model: str, llm_kwargs: dict[str, object]) -> None:
    """Raise max_tokens to a safe floor for thinking models using max() semantics.

    An unset budget gets the floor as is. A configured cap below the floor is raised, but never
    past the model's known output ceiling: the cap was accepted by the provider, the floor may not be.
    """
    floor = get_model_headroom_floor(model, llm_kwargs)
    if floor is None:
        return

    effort = extract_reasoning_effort(llm_kwargs)
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

    raised = clamp_budget_to_model_ceiling(model, floor, accepted=current)
    if raised > current:
        llm_kwargs["max_tokens"] = raised
        logger.info(
            "Thinking headroom: raised max_tokens %d -> %d for %s (effort=%s)",
            current,
            raised,
            model,
            effort or "default",
        )
