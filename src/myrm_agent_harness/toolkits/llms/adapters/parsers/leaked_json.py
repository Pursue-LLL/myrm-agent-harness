"""Leaked raw JSON tool call parsing (e.g. Gemini / Llama raw JSON in text).

[INPUT]
- contextlib (POS: Python contextlib utilities)
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)
- uuid::uuid4 (POS: UUID generator)
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- _parse_leaked_json_tool_calls_format(): leaked JSON tool call parsing.

[POS]
Leaked-JSON tool-call parser for models that emit raw JSON in text.
"""

from __future__ import annotations

import contextlib
import json
import re
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.types import ToolCallDict


def _parse_leaked_json_tool_calls_format(
    content: str,
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Parse tool calls leaked as raw JSON in message content.

    Handles formats:
    - {"tool_calls": [{"name": "foo", "arguments": {...}}]}
    - {"tool_calls": [{"function": {"name": "foo", "arguments": {...}}}]}
    - Markdown-wrapped ```json {"tool_calls": [...]} ```
    - Single tool call dict: {"name": "foo", "arguments": {...}} if name in available_tools
    """
    if not content or ("tool_calls" not in content and "name" not in content):
        return []

    stripped = content.strip()
    json_candidates: list[str] = []

    # Check for markdown code fences
    fence_pattern = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)
    fences = fence_pattern.findall(stripped)
    if fences:
        json_candidates.extend(fences)

    # Check if the whole content or a substring is a JSON object
    if stripped.startswith("{") and stripped.endswith("}"):
        json_candidates.append(stripped)
    else:
        # Scan for balanced or top-level JSON objects containing "tool_calls" or "name"
        obj_pattern = re.compile(r"(\{\s*\"tool_calls\"\s*:\s*\[[\s\S]*?\]\s*\})", re.IGNORECASE)
        for match in obj_pattern.findall(stripped):
            json_candidates.append(match)

    tool_calls: list[ToolCallDict] = []
    seen_signatures: set[str] = set()

    for candidate in json_candidates:
        parsed_obj: object = None
        with contextlib.suppress(Exception):
            parsed_obj = json.loads(candidate)

        if not isinstance(parsed_obj, dict):
            continue

        raw_calls: list[object] = []
        if "tool_calls" in parsed_obj and isinstance(parsed_obj["tool_calls"], list):
            raw_calls.extend(parsed_obj["tool_calls"])
        elif "name" in parsed_obj and isinstance(parsed_obj["name"], str):
            raw_calls.append(parsed_obj)

        for item in raw_calls:
            if not isinstance(item, dict):
                continue

            tool_name = ""
            args_val: object = None

            if "function" in item and isinstance(item["function"], dict):
                fn = item["function"]
                tool_name = str(fn.get("name", "")).strip()
                args_val = fn.get("arguments", {})
            elif "name" in item and isinstance(item["name"], str):
                tool_name = item["name"].strip()
                args_val = item.get("arguments", {})

            if not tool_name:
                continue

            # Verify against available_tools when available
            if available_tools and tool_name not in available_tools:
                continue

            # Serialize arguments safely
            if isinstance(args_val, dict):
                args_str = json.dumps(args_val, ensure_ascii=False)
            elif isinstance(args_val, str):
                args_str = args_val
            else:
                args_str = json.dumps(args_val or {}, ensure_ascii=False)

            sig = f"{tool_name}:{args_str}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            call_id = item.get("id")
            if not call_id or not isinstance(call_id, str):
                call_id = f"call_{uuid4().hex[:24]}"

            tool_calls.append(
                {
                    "id": call_id,
                    "index": len(tool_calls),
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": args_str,
                    },
                }
            )

    return tool_calls
