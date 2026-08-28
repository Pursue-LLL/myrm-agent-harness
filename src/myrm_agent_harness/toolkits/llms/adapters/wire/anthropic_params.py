"""Apply anthropic messages wire overrides for LiteLLM calls."""

from __future__ import annotations

from typing import Any


def apply_anthropic_messages_params(params: dict[str, Any]) -> dict[str, Any]:
    """Rewrite OpenCode Go chat model ids to Anthropic Messages API via LiteLLM."""
    merged = dict(params)
    model = str(merged.get("model") or "")
    bare = model.rsplit("/", 1)[-1] if "/" in model else model
    merged["model"] = f"anthropic/{bare}"
    merged["custom_llm_provider"] = "anthropic"
    return merged
