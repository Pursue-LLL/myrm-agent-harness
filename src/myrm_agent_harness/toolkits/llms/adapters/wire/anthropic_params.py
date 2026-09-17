"""Apply anthropic messages wire overrides for LiteLLM calls.

[INPUT]
- typing::Any (POS: Python 类型标注标准库)

[OUTPUT]
- apply_anthropic_messages_params: a copied params dict whose `model` is rewritten to
  `anthropic/<bare-id>` with `custom_llm_provider="anthropic"`

[POS]
Vendor override helper for the Anthropic Messages wire. Kept separate from the Responses
path because it only rewrites routing fields and never touches message translation. The
input dict is not mutated; a merged copy is returned.
"""

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
