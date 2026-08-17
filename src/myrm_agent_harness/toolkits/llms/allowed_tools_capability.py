"""OpenAI ``allowed_tools`` tool_choice capability helpers.

[INPUT]
- toolkits.llms.capability_learner::get_capability_learner (POS: runtime capability cache)

[OUTPUT]
- CAPABILITY_REJECTS_ALLOWED_TOOLS: learner key for unsupported tool_choice payloads
- normalize_model_capability_key(): stable learner key for model + optional API base
- model_supports_allowed_tools_tool_choice(): whether to send allowed_tools this call

[POS]
Provider capability gate for cache-safe skill attenuation. Execution-layer policy
remains authoritative when the model-layer hint is skipped. Gate also matches
gateway api_base markers (e.g. minimax, agnes).
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.llms.capability_learner import get_capability_learner

CAPABILITY_REJECTS_ALLOWED_TOOLS = "rejects_allowed_tools_tool_choice"

_OPENAI_LIKE_PREFIX = "openai-like/"
_MINIMAX_PREFIX = "minimax/"
_MINIMAX_API_BASE_MARKERS = ("minimaxi.com", "minimax.io")
_AGNES_API_BASE_MARKERS = ("agnes-ai.com", "apihub.agnes")
_OPENCODE_API_BASE_MARKERS = ("opencode.ai",)
_LOCAL_API_BASE_MARKERS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def normalize_model_capability_key(
    model_name: str,
    *,
    api_base: str | None = None,
) -> str:
    """Normalize model + optional API base into a stable capability learner key."""
    model = model_name.strip().lower()
    if not model:
        return model
    api = (api_base or "").strip().lower().rstrip("/")
    if not api:
        return model
    return f"{model}@{api}"


def model_supports_allowed_tools_tool_choice(
    model_name: str | None,
    *,
    api_base: str | None = None,
) -> bool:
    """Return True when the provider likely accepts ``tool_choice.type=allowed_tools``."""
    # Fail-closed by default: ``allowed_tools`` is a non-standard OpenAI extension
    # that only native OpenAI endpoints accept. Unknown/local/self-hosted proxies
    # reject it (LiteLLM → APIConnectionError "Invalid tool choice"), so we opt-in
    # for api.openai.com and let the learner cache mark any gateway that rejects it
    # (one retry) for the rest of the process. Execution-layer
    # check_trust_attenuation remains authoritative when the hint is skipped.
    if not model_name:
        return False

    normalized = normalize_model_capability_key(model_name, api_base=api_base)
    if not normalized:
        return False

    learner = get_capability_learner()
    if learner.get(normalized, CAPABILITY_REJECTS_ALLOWED_TOOLS, False) is True:
        return False

    api = (api_base or "").lower()

    # Local dev proxies never support the extension.
    if any(marker in api for marker in _LOCAL_API_BASE_MARKERS):
        return False

    if normalized.startswith(_OPENAI_LIKE_PREFIX):
        return False

    if normalized.startswith(_MINIMAX_PREFIX):
        return False

    if any(marker in api for marker in _MINIMAX_API_BASE_MARKERS):
        return False

    if any(marker in api for marker in _AGNES_API_BASE_MARKERS):
        return False

    # opencode.go / OpenCode gateway does NOT understand allowed_tools.
    if any(marker in api for marker in _OPENCODE_API_BASE_MARKERS):
        return False

    # Native OpenAI (api.openai.com) supports allowed_tools.
    if "api.openai.com" in api:
        return True

    return False
