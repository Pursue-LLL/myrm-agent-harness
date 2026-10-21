"""OpenAI model family reasoning_effort parameter remap and normalization.

[INPUT]
- model identifier, base_url, llm_kwargs dictionary

[OUTPUT]
- apply_openai_reasoning_effort(): remaps unsupported reasoning intensity values
  (e.g., 'minimal' -> 'low', 'xhigh'/'max' -> 'high') for OpenAI reasoning models
  (GPT-5.6, o1, o3, o4), and cleanly strips reasoning_effort from non-reasoning models
  (e.g., gpt-4o, gpt-4o-mini) to prevent API HTTP 400 Bad Request rejections.

[POS]
OpenAI reasoning models (such as o1, o3-mini, and GPT-5.6) natively accept only standard
``reasoning_effort`` values: ('low', 'medium', 'high'). Passing unsupported levels
such as 'minimal' (used by some frontends and agents for ultra-fast light thinking)
or 'max'/'xhigh' causes OpenAI's API to fail with HTTP 400 Bad Request.
Furthermore, non-reasoning models (such as gpt-4o and gpt-4o-mini) reject the
``reasoning_effort`` parameter entirely; if inadvertently injected into ``extra_body``,
strict gateways reject the request with HTTP 400.
This module remaps non-standard reasoning levels to OpenAI's valid enum and strips
the parameter for non-reasoning models, guaranteeing semantic intent preservation and zero 400s.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_OPENAI_PREFIXES: tuple[str, ...] = ("openai/", "azure/")
_OPENAI_HOSTS: tuple[str, ...] = ("api.openai.com",)

_OPENAI_REASONING_SUBSTRINGS: tuple[str, ...] = (
    "o1",
    "o3",
    "o4",
    "gpt-5",
    "gpt-5.6",
    "codex-reasoning",
)

_LOW_VALUES: frozenset[str] = frozenset({"low", "minimal", "min"})
_MEDIUM_VALUES: frozenset[str] = frozenset({"medium", "standard", "normal", "balanced"})
_HIGH_VALUES: frozenset[str] = frozenset({"high", "max", "xhigh", "ultra"})
_OFF_VALUES: frozenset[str] = frozenset({"off", "none", "disabled", "false", "0"})


def is_openai_model(model: str, base_url: str | None = None) -> bool:
    """Return True when the model belongs to the OpenAI family and is not routed via OpenRouter or DeepSeek."""
    if not model or model.startswith("openrouter/") or model.startswith("deepseek/"):
        return False
    lower = model.lower()
    if lower.startswith(_OPENAI_PREFIXES) or "openai/" in lower:
        return True
    if lower.startswith(("gpt-", "o1", "o3", "o4", "chatgpt-")):
        return True
    if base_url:
        b_lower = base_url.lower()
        if any(h in b_lower for h in _OPENAI_HOSTS):
            return True
    return False


def is_openai_reasoning_model(model: str) -> bool:
    """Check if the model is an OpenAI reasoning model that supports reasoning_effort."""
    lower = model.lower()
    clean = lower.split("/")[-1]
    for prefix in ("o1", "o3", "o4", "gpt-5"):
        if clean.startswith(prefix) or f"-{prefix}" in clean:
            return True
    return any(sub in clean for sub in _OPENAI_REASONING_SUBSTRINGS)


def apply_openai_reasoning_effort(model: str, llm_kwargs: dict[str, Any]) -> None:
    """Remap or strip reasoning_effort parameter for OpenAI family models in place.

    1. For OpenAI reasoning models (o1, o3, o4, gpt-5):
       - 'minimal' / 'min' -> 'low'
       - 'max' / 'xhigh' / 'ultra' -> 'high'
       - 'standard' / 'normal' / 'balanced' -> 'medium'
       - 'off' / 'none' / '0' -> stripped (OpenAI rejects 'off' on reasoning models)
    2. For OpenAI non-reasoning models (gpt-4o, gpt-4o-mini, gpt-3.5):
       - Strips reasoning_effort from both top-level kwargs and extra_body to avoid HTTP 400.
    """
    base_url = llm_kwargs.get("api_base") or llm_kwargs.get("base_url")
    if not is_openai_model(model, base_url):
        return

    extra_body = llm_kwargs.setdefault("extra_body", {})
    raw_effort = llm_kwargs.get("reasoning_effort")
    if raw_effort is None and isinstance(extra_body, dict):
        raw_effort = extra_body.get("reasoning_effort")

    if raw_effort is None:
        return

    # Case 1: Non-reasoning model rejects reasoning_effort parameter entirely
    if not is_openai_reasoning_model(model):
        llm_kwargs.pop("reasoning_effort", None)
        if isinstance(extra_body, dict):
            extra_body.pop("reasoning_effort", None)
        logger.debug("Stripped reasoning_effort for non-reasoning OpenAI model: %s", model)
        return

    # Case 2: Reasoning model (o1, o3, gpt-5) -> Remap to valid enum ('low', 'medium', 'high')
    norm_val = str(raw_effort).strip().lower()

    if norm_val in _OFF_VALUES:
        llm_kwargs.pop("reasoning_effort", None)
        if isinstance(extra_body, dict):
            extra_body.pop("reasoning_effort", None)
        logger.debug(
            "Stripped unsupported 'off' reasoning_effort for OpenAI reasoning model: %s",
            model,
        )
        return

    if norm_val in _LOW_VALUES:
        mapped_effort = "low"
    elif norm_val in _MEDIUM_VALUES:
        mapped_effort = "medium"
    elif norm_val in _HIGH_VALUES:
        mapped_effort = "high"
    else:
        # Fallback to provider default if value is unrecognized
        mapped_effort = "medium"

    llm_kwargs["reasoning_effort"] = mapped_effort
    if isinstance(extra_body, dict):
        extra_body["reasoning_effort"] = mapped_effort

    if norm_val != mapped_effort:
        logger.info(
            "Remapped reasoning_effort '%s' -> '%s' for OpenAI model %s",
            raw_effort,
            mapped_effort,
            model,
        )
