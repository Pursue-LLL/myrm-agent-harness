"""LiteLLM routing table and HTTP selection normalization (single source of truth).

[INPUT]
- (none) Pure data + string transforms.

[OUTPUT]
- BUILTIN_PROVIDER_LITELLM_SEGMENT: settings UI provider id -> LiteLLM first path segment
- CUSTOM_COMPAT_TYPE_LITELLM_SEGMENT: custom compat type id -> LiteLLM first path segment
- litellm_route_prefix_for_effective: provider or provider_type -> prefix ending with ``/``
- normalize_env_model_selection_string: env/model-picker style string -> LiteLLM model id
- known_litellm_route_segments_ordered: unique segments, longest first (UI + codegen)

[POS]
Framework routing authority shared with server tests and generated frontend constants.
"""

from __future__ import annotations

BUILTIN_PROVIDER_LITELLM_SEGMENT: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "deepseek": "deepseek",
    "openrouter": "openrouter",
    "zai": "zai",
    "xai": "xai",
    "ollama": "ollama",
    "moonshot": "moonshot",
    "lm_studio": "lm_studio",
    "mistral": "mistral",
    "together_ai": "together_ai",
    "siliconflow": "openai",
    "volcengine": "volcengine",
    "fireworks_ai": "fireworks_ai",
    "minimax": "minimax",
    "groq": "groq",
    "dashscope": "dashscope",
    "azure": "azure",
    "spark": "openai",
    "perplexity": "perplexity",
    "cohere_chat": "cohere_chat",
    "replicate": "replicate",
    "bedrock": "bedrock",
    "cerebras": "cerebras",
    "xiaomi_mimo": "xiaomi_mimo",
}

CUSTOM_COMPAT_TYPE_LITELLM_SEGMENT: dict[str, str] = {
    "openai-like": "openai",
    "gemini-like": "gemini",
    "anthropic-like": "anthropic",
}

_OPENAI_ROUTE_FAMILY: frozenset[str] = frozenset(
    {
        "openai",
        "siliconflow",
        "spark",
        "openai_compatible",
        "openai_like",
    }
)

_GEMINI_ROUTE_FAMILY: frozenset[str] = frozenset(
    {
        "gemini_compatible",
        "gemini_like",
    }
)

_ANTHROPIC_ROUTE_FAMILY: frozenset[str] = frozenset(
    {
        "anthropic_compatible",
        "anthropic_like",
    }
)

# First path segment in BASIC_MODEL / modelSelection (hyphen-normalized) -> LiteLLM route segment
_HTTP_SELECTION_FIRST_SEGMENT: dict[str, str] = {
    "openai-like": "openai",
    "openai-compatible": "openai",
    "siliconflow": "openai",
    "gemini-like": "gemini",
    "anthropic-like": "anthropic",
    "xiaomi": "xiaomi_mimo",
    "xiaomi_mimo": "xiaomi_mimo",
}


def litellm_route_prefix_for_effective(effective: str) -> str:
    """Return LiteLLM prefix (always ends with ``/``) for a provider or provider_type string."""
    key = effective.replace("-", "_").lower()
    if key == "openai":
        return "openai/"
    if key in _OPENAI_ROUTE_FAMILY:
        return "openai/"
    if key in _GEMINI_ROUTE_FAMILY:
        return "gemini/"
    if key in _ANTHROPIC_ROUTE_FAMILY:
        return "anthropic/"
    if key == "minimax":
        return "minimax/"
    if key == "xiaomi_mimo":
        return "xiaomi_mimo/"
    return f"{effective}/"


def normalize_env_model_selection_string(model: str) -> str:
    """Rewrite the first path segment to a LiteLLM route segment when it is a known alias.

    Used for HTTP ``modelSelection.model`` strings and test env ``BASIC_MODEL`` / ``LITE_MODEL``.
    """
    s = model.strip()
    if "/" not in s:
        return s
    left, right = s.split("/", 1)
    key = left.lower().replace("_", "-")
    route = _HTTP_SELECTION_FIRST_SEGMENT.get(key)
    if route:
        return f"{route}/{right}"
    return s


def known_litellm_route_segments_ordered() -> tuple[str, ...]:
    """Distinct route segments, longest-first then lexicographic (stable tie-break)."""
    segments: set[str] = set(BUILTIN_PROVIDER_LITELLM_SEGMENT.values())
    segments.update(CUSTOM_COMPAT_TYPE_LITELLM_SEGMENT.values())
    return tuple(sorted(segments, key=lambda x: (-len(x), x)))


__all__ = [
    "BUILTIN_PROVIDER_LITELLM_SEGMENT",
    "CUSTOM_COMPAT_TYPE_LITELLM_SEGMENT",
    "known_litellm_route_segments_ordered",
    "litellm_route_prefix_for_effective",
    "normalize_env_model_selection_string",
]
