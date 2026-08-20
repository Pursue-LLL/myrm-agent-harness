"""OpenAI Responses API native server-side compaction bridge.

[INPUT]
- none (pure protocol and helper types)

[OUTPUT]
- NativeCompactionItem: Encrypted compaction item schema
- is_eligible_native_compaction_route: Check if route + model supports native compaction
- build_responses_compaction_params: Build context_management parameter dict
- parse_compaction_from_response: Extract compaction items from API response dict/chunks

[POS]
Adapter utilities for OpenAI Responses API server-side compaction (/v1/responses).
Provides model gating, parameter injection, and stream event extraction without
coupling to the server or UI layers.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_GPT56_FAMILY_PATTERN = re.compile(
    r"^(?:openai/)?(?:gpt-5\.6|gpt-5\.5|gpt-5\.4|gpt-5\.3|gpt-5|codex)",
    re.IGNORECASE,
)

_OPENAI_DIRECT_DOMAINS = (
    "api.openai.com",
    "chatgpt.com",
    "oaistatic.com",
)


@dataclass(slots=True, frozen=True)
class NativeCompactionItem:
    """Encrypted compaction item returned by OpenAI Responses API."""

    item_id: str
    encrypted_payload: str
    created_at: int = 0
    compact_threshold: int = 200_000
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "compaction",
            "id": self.item_id,
            "encrypted_payload": self.encrypted_payload,
            "created_at": self.created_at,
            "compact_threshold": self.compact_threshold,
            "model": self.model,
        }


def is_eligible_native_compaction_route(
    model: str,
    api_base: str | None = None,
    custom_llm_provider: str | None = None,
) -> bool:
    """Check if model and endpoint route are eligible for native server-side compaction.

    Requires:
    1. Model belongs to gpt-5.6 / gpt-5 family or codex.
    2. Provider is direct OpenAI (or api_base points to api.openai.com / chatgpt.com / empty default).
    """
    if not model or not _GPT56_FAMILY_PATTERN.search(model):
        return False

    if custom_llm_provider and custom_llm_provider.lower() not in ("openai", "custom_openai"):
        return False

    if not api_base:
        return True

    api_base_lower = api_base.lower()
    return any(domain in api_base_lower for domain in _OPENAI_DIRECT_DOMAINS)


def build_responses_compaction_params(
    compact_threshold: int = 200_000,
    store: bool = False,
) -> dict[str, Any]:
    """Build kwargs for Responses API with server-side compaction enabled.

    Args:
        compact_threshold: Token count threshold at which server triggers compaction.
        store: Whether OpenAI should retain request data (default False for ZDR compliance).
    """
    return {
        "context_management": [
            {
                "type": "compaction",
                "compact_threshold": max(50_000, compact_threshold),
            }
        ],
        "store": store,
    }


def parse_compaction_from_response(response_dict: dict[str, Any]) -> NativeCompactionItem | None:
    """Extract native compaction item from a completed response or chunk dict."""
    if not response_dict:
        return None

    # Check choices or output array (Responses API format)
    for choice in response_dict.get("choices") or []:
        delta = choice.get("delta") or choice.get("message") or {}
        compaction = delta.get("compaction") or delta.get("compaction_item")
        if isinstance(compaction, dict) and compaction.get("id"):
            return NativeCompactionItem(
                item_id=str(compaction["id"]),
                encrypted_payload=str(compaction.get("encrypted_payload") or compaction.get("payload") or ""),
                created_at=int(compaction.get("created_at") or 0),
                model=str(response_dict.get("model") or ""),
            )

    # Check top-level context_management or compaction items
    output_items = response_dict.get("output_items") or response_dict.get("items") or []
    for item in output_items:
        if isinstance(item, dict) and item.get("type") == "compaction":
            return NativeCompactionItem(
                item_id=str(item.get("id") or item.get("item_id") or ""),
                encrypted_payload=str(item.get("encrypted_payload") or item.get("payload") or ""),
                created_at=int(item.get("created_at") or 0),
                model=str(response_dict.get("model") or ""),
            )

    return None
