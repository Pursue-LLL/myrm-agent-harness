"""Detect calls that LiteLLM sends to Anthropic's own Messages API.

[INPUT]
- litellm::get_llm_provider (POS: provider resolution from model id, custom provider and api_base)

[OUTPUT]
- is_native_anthropic_wire: True when the call goes to the first-party Anthropic Messages API

[POS]
Wire-protocol probe that lets callers keep OpenAI-shaped pass-through fields off requests the Messages API rejects.
Anthropic models behind a gateway (OpenRouter, Bedrock, Vertex AI, ``openai/`` endpoints) and unclassifiable models are not native.
"""

from __future__ import annotations

_NATIVE_PROVIDER = "anthropic"


def is_native_anthropic_wire(
    model: str,
    api_base: str | None = None,
    custom_llm_provider: str | None = None,
) -> bool:
    """True when LiteLLM resolves this call to the first-party Anthropic Messages API.

    That API rejects unknown top-level fields ("<key>: Extra inputs are not permitted"), so such
    calls are left to LiteLLM's own Messages translation. A model LiteLLM cannot classify counts
    as not native and keeps the pass-through behaviour.
    """
    if not model:
        return False
    try:
        import litellm

        provider: str = litellm.get_llm_provider(
            model=model,
            custom_llm_provider=custom_llm_provider,
            api_base=api_base,
        )[1]
    except Exception:
        return False
    return provider == _NATIVE_PROVIDER
