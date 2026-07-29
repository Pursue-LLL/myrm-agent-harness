"""OpenAI ``allowed_tools`` tool_choice capability helpers.

[INPUT]
- toolkits.llms.capability_learner::get_capability_learner (POS: runtime capability cache)

[OUTPUT]
- CAPABILITY_REJECTS_ALLOWED_TOOLS: learner key for unsupported tool_choice payloads
- normalize_model_capability_key(): stable learner key for model identifiers
- model_supports_allowed_tools_tool_choice(): whether to send allowed_tools this call

[POS]
Provider capability gate for cache-safe skill attenuation. Execution-layer policy
remains authoritative when model-layer hint is skipped.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.capability_learner import get_capability_learner

CAPABILITY_REJECTS_ALLOWED_TOOLS = "rejects_allowed_tools_tool_choice"

_OPENAI_LIKE_PREFIX = "openai-like/"
_MINIMAX_PREFIX = "minimax/"
_MINIMAX_API_BASE_MARKERS = ("minimaxi.com", "minimax.io")


def normalize_model_capability_key(model_name: str) -> str:
    """Normalize model identifiers for capability learner keys."""
    return model_name.strip().lower()


def model_supports_allowed_tools_tool_choice(
    model_name: str | None,
    *,
    api_base: str | None = None,
) -> bool:
    """Return True when the provider likely accepts ``tool_choice.type=allowed_tools``."""
    if not model_name:
        return True

    normalized = normalize_model_capability_key(model_name)
    if not normalized:
        return True

    learner = get_capability_learner()
    if learner.get(normalized, CAPABILITY_REJECTS_ALLOWED_TOOLS, False) is True:
        return False

    if normalized.startswith(_OPENAI_LIKE_PREFIX):
        return False

    if normalized.startswith(_MINIMAX_PREFIX):
        return False

    api = (api_base or "").lower()
    if any(marker in api for marker in _MINIMAX_API_BASE_MARKERS):
        return False

    if "api.openai.com" in api:
        return True

    return True
