"""Model introspection utilities.

[INPUT]
- langchain_core.language_models.BaseChatModel (POS: LangChain LLM base class)

[OUTPUT]
- get_model_context_limit(): best-effort extraction of model context window size
- get_model_output_ceiling(): documented per-response output ceiling of a model, or None when unmapped
- clamp_budget_to_model_ceiling(): limit an upward output-budget adjustment to the known ceiling

[POS]
Stateless utilities for inspecting LLM model properties.
"""

from __future__ import annotations

from functools import lru_cache

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

    # Check extra_body options num_ctx (Ollama / Local endpoints)
    extra_body = getattr(llm, "extra_body", None)
    if isinstance(extra_body, dict):
        options = extra_body.get("options")
        if isinstance(options, dict):
            num_ctx = options.get("num_ctx")
            if isinstance(num_ctx, int) and num_ctx > 0:
                return num_ctx

    model_name = getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
    if not model_name:
        return None

    try:
        import litellm

        info = litellm.get_model_info(model_name)
        return info.get("max_input_tokens")
    except Exception:
        return None


@lru_cache(maxsize=512)
def get_model_output_ceiling(model_name: str) -> int | None:
    """Documented per-response output ceiling of *model_name*, or None when LiteLLM does not know it.

    Only ``max_output_tokens`` is trusted: for part of LiteLLM's table the legacy ``max_tokens``
    field holds the context window, which would turn a budget clamp into a no-op.
    """
    if not model_name:
        return None
    try:
        import litellm

        ceiling = litellm.get_model_info(model_name).get("max_output_tokens")
    except Exception:
        return None
    return ceiling if isinstance(ceiling, int) and ceiling > 0 else None


def clamp_budget_to_model_ceiling(model_name: str, requested: int, *, accepted: int) -> int:
    """Limit an upward output-budget adjustment to the model's known ceiling.

    ``accepted`` is a budget the provider already served: the caller's configured cap, or the
    base budget of a call that just truncated. A table ceiling below it is a stale entry rather
    than a limit, so the result never drops below ``accepted``; an unknown ceiling leaves
    ``requested`` untouched.
    """
    ceiling = get_model_output_ceiling(model_name)
    if ceiling is None:
        return requested
    return max(accepted, min(requested, ceiling))
