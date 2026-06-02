"""Model introspection utilities.

[INPUT]
- langchain_core.language_models.BaseChatModel (POS: LangChain LLM base class)

[OUTPUT]
- get_model_context_limit(): best-effort extraction of model context window size

[POS]
Stateless utilities for inspecting LLM model properties.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel


def get_model_context_limit(llm: BaseChatModel) -> int | None:
    """Best-effort extraction of the model's context window size.

    Returns None if the limit cannot be determined (graceful — skip the check).
    Only checks attributes that represent the input context window,
    never output-limit attributes like ``max_tokens``.
    """
    for attr in ("n_ctx", "model_max_context_length", "max_input_tokens"):
        val = getattr(llm, attr, None)
        if isinstance(val, int) and val > 0:
            return val

    model_name = getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
    if not model_name:
        return None

    try:
        import litellm

        info = litellm.get_model_info(model_name)
        return info.get("max_input_tokens")
    except Exception:
        return None
