"""OpenAI-format tool call parsing.

[INPUT]
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- _parse_openai_format(): standard OpenAI tool_calls parsing.

[POS]
Native OpenAI tool-call parser. Provider ids pass through verbatim;
only ids repeated within one batch are disambiguated (id@n).
"""

from __future__ import annotations

from typing import Any

from myrm_agent_harness.toolkits.llms.adapters.parsers.types import LLMResponseDict, ToolCallDict


def _parse_openai_format(
    response_dict: LLMResponseDict | dict[str, Any],
) -> list[ToolCallDict]:
    """Parse standard OpenAI-format tool call"""
    raw_tool_calls = response_dict.get("tool_calls")
    if not raw_tool_calls or not isinstance(raw_tool_calls, list):
        return []

    # Disambiguate only ids repeated within this batch: providers reject duplicate
    # tool_call ids, while gateways that validate provenance need the original id back.
    # The id@n suffix matches agent.middlewares.tooling.tool_history_hygiene so ids
    # stay deterministic and reproducible across layers.
    seen_counts: dict[str, int] = {}
    for tc in raw_tool_calls:
        original_id = tc.get("id")
        if not isinstance(original_id, str) or not original_id:
            continue
        seen_counts[original_id] = seen_counts.get(original_id, 0) + 1
        if seen_counts[original_id] > 1:
            tc["id"] = f"{original_id}@{seen_counts[original_id]}"

    return raw_tool_calls
