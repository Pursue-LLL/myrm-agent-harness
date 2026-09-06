"""Model tier inference — auto-detect model capability level.

Infers a capability tier (STRONG/MEDIUM/WEAK) from model name and optional
CustomModelDef metadata. Used by the server layer to auto-tune prompt mode,
parallel tool calls, and compression thresholds for small local models.
"""

from __future__ import annotations

import re
from enum import StrEnum

from myrm_agent_harness.core.config.llm import CustomModelDef

_WEAK_CONTEXT_THRESHOLD = 16_384
_MEDIUM_CONTEXT_THRESHOLD = 65_536

_PARAM_SIZE_PATTERN = re.compile(
    r"[:\-_](\d+(?:\.\d+)?)\s*[bB](?:[_\-:]|$)", re.IGNORECASE
)

_MEDIUM_MODEL_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "flash",
        "mini",
        "haiku",
        "lite",
        "turbo",
        "small",
    }
)

_STRONG_MODEL_SUBSTRINGS: frozenset[str] = frozenset(
    {
        "gpt-4",
        "gpt-4o",
        "gpt-4.1",
        "claude-3.5",
        "claude-3-opus",
        "claude-4",
        "gemini-1.5-pro",
        "gemini-2-pro",
        "gemini-2.5-pro",
        "gemini-pro",
        "deepseek-v3",
        "deepseek-r1",
        "qwen-max",
        "qwen3-235b",
    }
)


class ModelTier(StrEnum):
    """Model capability tier for auto-tuning agent behavior."""

    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"


def infer_model_tier(
    model_name: str,
    custom_model_def: CustomModelDef | None = None,
    max_context_tokens: int | None = None,
) -> ModelTier:
    """Infer model capability tier from model name and metadata.

    Priority:
        1. Explicit context_length from CustomModelDef or max_context_tokens
        2. Parameter count extracted from model name (e.g. "qwen2.5:7b")
        3. Known strong model substring matching
        4. Default to STRONG (cloud API models without size info are assumed strong)
    """
    context_length = _resolve_context_length(custom_model_def, max_context_tokens)

    if context_length is not None:
        if context_length <= _WEAK_CONTEXT_THRESHOLD:
            return ModelTier.WEAK
        if context_length <= _MEDIUM_CONTEXT_THRESHOLD:
            return ModelTier.MEDIUM
        return ModelTier.STRONG

    nl = model_name.lower()
    # Specific high-capability model families take precedence over general size substrings
    for s in _STRONG_MODEL_SUBSTRINGS:
        if s in nl:
            # Specific known low/medium variants within strong families (e.g. gpt-4o-mini, gemini-2.0-flash)
            # Only trigger medium if the variant marker is present and the model is not explicitly marked "pro" or "max"
            if any(m in nl for m in ("mini", "flash", "haiku")) and not any(
                p in nl for p in ("pro", "max", "opus")
            ):
                return ModelTier.MEDIUM
            return ModelTier.STRONG

    param_billions = _extract_param_size(model_name)
    if param_billions is not None:
        if param_billions <= 14:
            return ModelTier.WEAK
        if param_billions <= 35:
            return ModelTier.MEDIUM
        return ModelTier.STRONG

    if any(m in nl for m in _MEDIUM_MODEL_SUBSTRINGS):
        return ModelTier.MEDIUM

    return ModelTier.STRONG


def _resolve_context_length(
    custom_model_def: CustomModelDef | None,
    max_context_tokens: int | None,
) -> int | None:
    if custom_model_def is not None and custom_model_def.context_length > 0:
        return custom_model_def.context_length
    return max_context_tokens


def _extract_param_size(model_name: str) -> float | None:
    """Extract parameter size in billions from model name patterns.

    Matches: "qwen2.5:7b", "llama3-8b", "mistral_7b", "phi-3.5:3.8b"
    """
    # Guard against version numbers like "gemini-1.5-pro", "gpt-4.1" being parsed as param sizes
    match = _PARAM_SIZE_PATTERN.search(model_name)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass

    return None
