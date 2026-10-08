"""Detect calls that LiteLLM sends to Anthropic's own Messages API.

[INPUT]
- litellm::get_llm_provider (POS: provider resolution from model id, custom provider and api_base)

[OUTPUT]
- is_native_anthropic_wire: True when the call goes to the first-party Anthropic Messages API

[POS]
The Messages API rejects unknown top-level request fields ("<key>: Extra inputs are not permitted"),
while OpenAI-compatible gateways tolerate them. Callers use this to keep OpenAI-shaped pass-through
parameters off the Anthropic request body and let LiteLLM's own Messages translation build it.
Anthropic models served through a gateway (OpenRouter, Bedrock, Vertex AI, an ``openai/`` custom
endpoint) resolve to a different provider and keep the pass-through behaviour. A model LiteLLM
cannot classify is treated as not native, which preserves the pass-through behaviour.
"""

from __future__ import annotations

from functools import lru_cache

_NATIVE_PROVIDER = "anthropic"


@lru_cache(maxsize=512)
def is_native_anthropic_wire(
    model: str,
    api_base: str | None = None,
    custom_llm_provider: str | None = None,
) -> bool:
    """True when LiteLLM resolves this call to the first-party Anthropic Messages API."""
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
