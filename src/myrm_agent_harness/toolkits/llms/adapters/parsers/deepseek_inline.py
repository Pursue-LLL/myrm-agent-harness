"""DeepSeek inline tool call parsing.

[INPUT]
- adapters.parsers.types (POS: tool-call type definitions)
- adapters.parsers.json_scanner (POS: code-block and JSON boundary scanning)

[OUTPUT]
- _parse_deepseek_inline_format(): DeepSeek inline tool call parsing.

[POS]
DeepSeek inline-format tool-call parser.
"""

from __future__ import annotations

import json
import logging
import re
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.json_scanner import (
    _find_json_object_end,
    _is_inside_code_block,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.types import ToolCallDict

logger = logging.getLogger(__name__)


def _parse_deepseek_inline_format(
    content: str,
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Parse DeepSeek inline format tool calls

    Format example:
    tool_name {"arg1": "value1", "arg2": "value2"}
    """
    if not content or not isinstance(content, str):
        return []

    if not available_tools:
        return []

    pattern = r"([a-zA-Z_][a-zA-Z0-9_]*)\s*\{"
    matches = list(re.finditer(pattern, content))
    if not matches:
        return []

    extracted_calls: list[ToolCallDict] = []

    for match in matches:
        tool_name = match.group(1)
        if tool_name not in available_tools:
            continue

        if _is_inside_code_block(content, match.start()):
            logger.debug(f" Skipping tool call match inside code block: {tool_name}")
            continue

        before_match = content[: match.start()].rstrip()
        if before_match and before_match[-1] in ('"', "'", "`"):
            logger.debug(f" Skipping tool call match inside quotes: {tool_name}")
            continue

        json_start = match.start() + len(tool_name)
        remaining = content[json_start:].strip()

        if not remaining.startswith("{"):
            continue

        # Find the end position of a JSON object
        end_pos = _find_json_object_end(remaining)
        if end_pos <= 0:
            continue

        json_str = remaining[:end_pos]

        try:
            args = json.loads(json_str)
            if not isinstance(args, dict):
                continue

            tool_call: ToolCallDict = {
                "id": f"call_{uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args, sort_keys=True),
                },
            }
            extracted_calls.append(tool_call)
            logger.debug(f" DeepSeek inline parsed: {tool_name}")

        except (json.JSONDecodeError, TypeError):
            continue

    return extracted_calls
