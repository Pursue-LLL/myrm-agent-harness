"""GLM XML tool call parsing (reasoning_content tool_call tags).

[INPUT]
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)
- uuid::uuid4 (POS: UUID generator)
- logging (POS: Python logging)
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- _parse_glm_xml_format(): GLM XML tool call parsing.

[POS]
GLM-family XML tool-call parser.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.types import ToolCallDict

logger = logging.getLogger(__name__)


def _parse_glm_xml_format(reasoning_content: str) -> list[ToolCallDict]:
    """Parse GLM XML format tool calls

    Format example:
    <tool_call>tool_name
    <arg_key>key1</arg_key>
    <arg_value>value1</arg_value>
    </tool_call>
    """
    if not reasoning_content or "<tool_call>" not in reasoning_content:
        return []

    tool_calls: list[ToolCallDict] = []

    # Match tool_call block
    tool_call_pattern = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
    matches = tool_call_pattern.findall(reasoning_content)

    for idx, match in enumerate(matches):
        try:
            # Extract tool name (first line)
            lines = match.strip().split("\n")
            tool_name = lines[0].strip() if lines else ""

            if not tool_name:
                continue

            # Parse parameters
            args: dict[str, Any] = {}
            arg_key_pattern = re.compile(r"<arg_key>(.*?)</arg_key>", re.DOTALL)
            arg_value_pattern = re.compile(r"<arg_value>(.*?)</arg_value>", re.DOTALL)

            keys = arg_key_pattern.findall(match)
            values = arg_value_pattern.findall(match)

            for key, value in zip(keys, values, strict=False):
                key = key.strip()
                value = value.strip()

                # Try parsing JSON values (arrays, objects, etc.)
                try:
                    args[key] = json.loads(value)
                except json.JSONDecodeError:
                    args[key] = value

            # Build OpenAI-format tool_call
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

            logger.debug(f" GLM XML parsed: {tool_name}, args={args}")

        except Exception as e:
            logger.warning(f" GLM XML Parsing failed: {e}")
            continue

    return tool_calls
