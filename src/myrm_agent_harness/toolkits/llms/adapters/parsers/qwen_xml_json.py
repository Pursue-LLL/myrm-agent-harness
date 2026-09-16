"""Qwen XML JSON tool call parsing.

[INPUT]
- contextlib (POS: Python contextlib utilities)
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)
- uuid::uuid4 (POS: UUID generator)
- logging (POS: Python logging)
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- _parse_qwen_xml_json_format(): Qwen XML JSON tool call parsing.

[POS]
Qwen-family XML/JSON tool-call parser.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.types import ToolCallDict

logger = logging.getLogger(__name__)


def _parse_qwen_xml_json_format(
    content: str,
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Parse Qwen XML JSON format tool calls

    Format example:
    <tool_call> {"name": "tool_name", "arguments": {"arg1": "value1"}} </tool_call>
    """
    if not content or not isinstance(content, str):
        return []

    tool_calls: list[ToolCallDict] = []
    pattern = re.compile(r"<tool_call>\s*(\{.*?)(?:</tool_call>|$)", re.DOTALL)
    matches = pattern.findall(content)

    for idx, match in enumerate(matches):
        try:
            # Fix common JSON escaping issues (e.g., unescaped quotes inside string values)
            # This is a simple heuristic, a more robust parser might be needed for complex cases
            try:
                data = json.loads(match)
            except json.JSONDecodeError:
                import re as regex

                # Try to fix unescaped quotes: "key": ""value"" -> "key": "\"value\""
                fixed_match = regex.sub(r'(:\s*)""([^"]+)""', r'\1"\\"\2\\""', match)
                data = json.loads(fixed_match)

            tool_name = data.get("name")
            args = data.get("arguments", {})

            if not tool_name and "function" in data and isinstance(data["function"], dict):
                func_data = data["function"]
                tool_name = func_data.get("name")
                args = func_data.get("arguments", {})

            if not tool_name:
                continue

            if available_tools and tool_name not in available_tools:
                logger.debug(f" Qwen XML JSON tool call name not in available tools: {tool_name}")
                continue
            if isinstance(args, str):
                with contextlib.suppress(json.JSONDecodeError):
                    args = json.loads(args)
            elif not isinstance(args, dict):
                args = {}

            tool_call: ToolCallDict = {
                "id": f"call_{uuid4().hex[:24]}",
                "index": idx,
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
                "type": "function",
            }
            tool_calls.append(tool_call)
            logger.debug(f" Qwen XML JSON parsed: {tool_name}")

        except Exception as e:
            logger.warning(f" Qwen XML JSON Parsing failed: {e}")
            continue

    return tool_calls
