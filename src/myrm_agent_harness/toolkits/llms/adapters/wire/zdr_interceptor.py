"""Zero Data Retention (ZDR) wire interceptor for outbound LLM calls.

[INPUT]
- typing::dict, str, object (POS: Python 标准类型标注)

[OUTPUT]
- apply_zdr_outbound_params: Pure-function interceptor injecting vendor-standard
  Zero Data Retention headers and payload fields without modifying messages.
- is_zdr_eligible_provider: Predicate checking whether a provider/model wire supports ZDR.

[POS]
Harness-only protocol layer. Ensures enterprise compliance and zero data retention
on outbound wire calls across OpenAI, Azure, Anthropic, Bedrock, and compatible endpoints.
Prompt Cache byte-level 100% preserved (never touches messages or system prompt).
"""

from __future__ import annotations

import copy
from typing import Final

_OPENAI_VENDORS: Final[frozenset[str]] = frozenset(
    {"openai", "azure", "azure_ai", "openai-compatible"}
)
_ANTHROPIC_VENDORS: Final[frozenset[str]] = frozenset(
    {"anthropic", "claude"}
)
_BEDROCK_VENDORS: Final[frozenset[str]] = frozenset(
    {"bedrock", "aws-bedrock", "amazon-bedrock"}
)


def is_zdr_eligible_provider(provider_or_model: str) -> bool:
    """Check if the given provider or model identifier supports ZDR headers/flags."""
    if not provider_or_model:
        return False
    normalized = provider_or_model.strip().lower()
    return any(
        vendor in normalized
        for vendor in (
            "openai",
            "azure",
            "anthropic",
            "claude",
            "bedrock",
            "deepseek",
            "minimax",
            "qwen",
        )
    )


def apply_zdr_outbound_params(
    params: dict[str, object],
    *,
    provider: str = "",
    enabled: bool = True,
) -> dict[str, object]:
    """Inject Zero Data Retention (ZDR) parameters and headers into outbound call kwargs.

    Guarantees:
    1. Pure functional transformation (never mutates the input dictionary).
    2. Zero prompt pollution (never modifies messages or system instructions,
       preserving 100% byte-level Prompt Cache).
    3. Standards-compliant headers and top-level fields for OpenAI, Anthropic, Bedrock.

    Args:
        params: LiteLLM or direct wire completion kwargs.
        provider: Explicit provider hint if known (e.g. 'openai', 'anthropic').
        enabled: If False, returns a shallow copy of params untouched.

    Returns:
        New kwargs dictionary enriched with vendor-standard ZDR compliance attributes.
    """
    if not enabled:
        return copy.copy(params)

    enriched = copy.copy(params)
    inferred_provider = (
        provider
        or str(enriched.get("custom_llm_provider") or "")
        or str(enriched.get("model") or "")
    ).strip().lower()

    # 1. Base ZDR field for OpenAI / Azure / OpenAI-compatible Responses & Chat
    # Top-level 'store: False' instructs the vendor not to retain completions.
    enriched["store"] = False

    # 2. Extract or initialize extra_headers safely without mutating original
    raw_headers = enriched.get("extra_headers")
    extra_headers: dict[str, str] = {}
    if isinstance(raw_headers, dict):
        extra_headers = {str(k): str(v) for k, v in raw_headers.items()}

    # 3. Vendor-specific compliance headers
    if any(p in inferred_provider for p in _ANTHROPIC_VENDORS):
        extra_headers["Anthropic-Zero-Data-Retention"] = "true"
    elif any(p in inferred_provider for p in _BEDROCK_VENDORS):
        extra_headers["x-amzn-bedrock-zero-data-retention"] = "true"
    else:
        # Standard OpenAI/Azure compliance header
        extra_headers["X-OpenAI-Store"] = "false"

    enriched["extra_headers"] = extra_headers

    # 4. Optional extra_body metadata tagging (for audit tracking on proxies)
    raw_extra_body = enriched.get("extra_body")
    extra_body: dict[str, object] = {}
    if isinstance(raw_extra_body, dict):
        extra_body = copy.copy(raw_extra_body)

    # Attach compliance audit marker in extra_body for upstream proxy attestation
    extra_body["zdr_retention_policy"] = "zero_data_retention"
    enriched["extra_body"] = extra_body

    return enriched
