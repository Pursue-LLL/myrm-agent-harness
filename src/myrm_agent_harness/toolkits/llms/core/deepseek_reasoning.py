"""DeepSeek reasoning_effort and thinking protocol parameter mapping.

[INPUT]
- model identifier, base_url, llm_kwargs dictionary

[OUTPUT]
- apply_deepseek_reasoning_effort(): normalizes reasoning_effort and thinking
  configuration for DeepSeek models (native deepseek, deepseek-v4-pro, deepseek-r1).

[POS]
DeepSeek API natively accepts reasoning intensity via ``reasoning_effort``
with valid levels ('low', 'high', 'max') and controls reasoning mode via
``thinking: {"type": "enabled" | "disabled"}`` for models that support configurable thinking
(such as DeepSeek-V4-Pro and DeepSeek-V4-Flash).
Always-on reasoning models (such as DeepSeek-R1 and deepseek-reasoner) do not accept
``reasoning_effort`` or ``thinking`` parameters from caller requests; passing them causes HTTP 400.
LiteLLM requires ``thinking: {"type": "enabled"}`` on configurable models to activate its thinking
mode and protect multi-turn tool-calling with ``reasoning_content``.
This module maps standard/extended reasoning effort values to DeepSeek native
parameters and guarantees thinking mode activation or deactivation without HTTP 400 errors.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_DEEPSEEK_PREFIXES: tuple[str, ...] = ("deepseek/",)
_DEEPSEEK_HOSTS: tuple[str, ...] = ("api.deepseek.com",)
_ALWAYS_ON_MODEL_SUBSTRINGS: tuple[str, ...] = (
    "deepseek-reasoner",
    "deepseek-r1",
    "/r1",
)

_CONFIGURABLE_REASONING_SUBSTRINGS: tuple[str, ...] = (
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4",
)

_OFF_VALUES: frozenset[str] = frozenset({"off", "none", "disabled", "false", "0"})
_MAX_VALUES: frozenset[str] = frozenset({"max", "xhigh", "ultra"})
_HIGH_VALUES: frozenset[str] = frozenset({"high", "medium", "standard", "normal"})
_LOW_VALUES: frozenset[str] = frozenset({"low", "min"})


def is_deepseek_model(model: str, base_url: str | None = None) -> bool:
    """Return True when the model or endpoint belongs to DeepSeek.

    OpenRouter-routed models are excluded since they use OpenRouter's
    own reasoning.effort protocol via apply_openrouter_reasoning_effort.
    """
    if not model or model.startswith("openrouter/"):
        return False
    lower = model.lower()
    if lower.startswith("deepseek") or any(lower.startswith(p) for p in _DEEPSEEK_PREFIXES) or "deepseek/" in lower:
        return True
    if base_url:
        b_lower = base_url.lower()
        if any(h in b_lower for h in _DEEPSEEK_HOSTS):
            return True
    return False


def is_deepseek_always_on_reasoning_model(model: str) -> bool:
    """Check if model is an always-on reasoning model (R1/Reasoner) that rejects reasoning_effort params."""
    lower = model.lower()
    return any(sub in lower for sub in _ALWAYS_ON_MODEL_SUBSTRINGS)


def is_deepseek_reasoning_model(model: str) -> bool:
    """Check if the model name indicates any thinking/reasoning model."""
    lower = model.lower()
    return is_deepseek_always_on_reasoning_model(model) or any(
        sub in lower for sub in _CONFIGURABLE_REASONING_SUBSTRINGS
    )


def apply_deepseek_reasoning_effort(model: str, llm_kwargs: dict[str, Any]) -> None:
    """Normalize reasoning effort and thinking parameters for DeepSeek models.

    1. For always-on models (deepseek-r1, deepseek-reasoner):
       Strips any reasoning_effort and thinking parameters to prevent API HTTP 400.
    2. For configurable models (deepseek-v4-pro, deepseek-v4-flash):
       - When effort is 'off' / 'none' / 'disabled':
         Injects extra_body.thinking = {"type": "disabled"} and strips reasoning_effort.
       - When effort is 'low', 'high', 'max' (or smooth mappings like medium -> high):
         Injects extra_body.thinking = {"type": "enabled"} and passes the native effort.
       - When effort is None:
         Injects extra_body.thinking = {"type": "enabled"} so LiteLLM activates thinking
         mode and automatically protects multi-turn tool-calling with reasoning_content.

    Args:
        model: Model identifier (e.g. 'deepseek/deepseek-v4-pro').
        llm_kwargs: Mutable LLM parameter dict (modified in place).
    """
    base_url = llm_kwargs.get("api_base") or llm_kwargs.get("base_url")
    if not is_deepseek_model(model, base_url):
        return

    extra_body = llm_kwargs.setdefault("extra_body", {})
    if not isinstance(extra_body, dict):
        extra_body = {}
        llm_kwargs["extra_body"] = extra_body

    # Case 1: Always-on reasoning models (R1/Reasoner) reject reasoning_effort & thinking params
    if is_deepseek_always_on_reasoning_model(model):
        llm_kwargs.pop("reasoning_effort", None)
        extra_body.pop("reasoning_effort", None)
        extra_body.pop("thinking", None)
        logger.debug("Stripped reasoning_effort/thinking for always-on DeepSeek reasoning model: %s", model)
        return

    # Extract effort from top-level or extra_body
    raw_effort = llm_kwargs.get("reasoning_effort")
    if raw_effort is None:
        raw_effort = extra_body.get("reasoning_effort")

    # Case 2: Configurable models with effort unspecified
    if raw_effort is None:
        if is_deepseek_reasoning_model(model) and "thinking" not in extra_body:
            extra_body["thinking"] = {"type": "enabled"}
            logger.debug("Auto-enabled thinking mode for DeepSeek configurable model: %s", model)
        return

    effort_str = str(raw_effort).strip().lower()

    # Case 3: effort explicitly disabled
    if effort_str in _OFF_VALUES:
        extra_body["thinking"] = {"type": "disabled"}
        extra_body.pop("reasoning_effort", None)
        llm_kwargs.pop("reasoning_effort", None)
        logger.info("DeepSeek reasoning disabled: model=%s", model)
        return

    # Case 4: effort enabled with level mapping
    mapped_effort: str
    if effort_str in _MAX_VALUES:
        mapped_effort = "max"
    elif effort_str in _HIGH_VALUES:
        mapped_effort = "high"
    elif effort_str in _LOW_VALUES:
        mapped_effort = "low"
    else:
        mapped_effort = "high"

    extra_body["thinking"] = {"type": "enabled"}
    extra_body["reasoning_effort"] = mapped_effort
    llm_kwargs["reasoning_effort"] = mapped_effort
    logger.info("DeepSeek reasoning mapped: model=%s raw=%s -> effort=%s", model, raw_effort, mapped_effort)
