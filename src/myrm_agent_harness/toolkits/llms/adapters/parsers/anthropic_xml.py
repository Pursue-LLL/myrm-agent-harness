"""Anthropic XML tool call parsing.

[INPUT]
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)
- uuid::uuid4 (POS: UUID generator)
- logging (POS: Python logging)
- adapters.parsers.types (POS: tool-call type definitions)
- adapters.parsers.json_scanner (POS: code-block and JSON boundary scanning)

[OUTPUT]
- _parse_anthropic_xml_format(): Anthropic XML tool call parsing.
- _parse_xml_parameter_value(): shared XML parameter value parser.

[POS]
Anthropic-family XML tool-call parser plus the shared XML parameter helper.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, cast
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.json_scanner import _is_inside_code_block
from myrm_agent_harness.toolkits.llms.adapters.parsers.types import ToolCallDict

logger = logging.getLogger(__name__)


def _parse_anthropic_xml_format(
    content: str,
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Parse Anthropic XML format tool calls

    Supports two formats:
    1. Standard format: <invoke name="tool">...</invoke>
    2. Prefixed format: <invoke name="tool">...</invoke>
    """
    if not content or not isinstance(content, str):
        return []

    # Match invoke tags (with or without antml: prefix)
    invoke_pattern = r'<(antml:)?invoke\s+name=["\']([^"\']+)["\']>(.*?)(?:</(antml:)?invoke>|$)'

    matches = list(re.finditer(invoke_pattern, content, re.DOTALL))
    if not matches:
        return []

    extracted_calls: list[ToolCallDict] = []

    for match in matches:
        tool_name = match.group(2)
        invoke_body = match.group(3)

        # Safety: validate tool name against available_tools if provided
        if available_tools and tool_name not in available_tools:
            logger.debug(f" XML tool call name not in available tools: {tool_name}")
            continue

        # Safety: skip matches inside code blocks
        if _is_inside_code_block(content, match.start()):
            logger.debug(f" Skipping XML tool call inside code block: {tool_name}")
            continue

        # Parse parameter tags
        param_pattern = (
            r'<(antml:)?parameter\s+name=["\']([^"\']+)["\'](?:\s+string=["\']([^"\']*)["\'])?>'
            r"([\s\S]*?)(?:</(antml:)?parameter>|$)"
        )

        params_matches = re.finditer(param_pattern, invoke_body)
        args: dict[str, Any] = {}

        for param_match in params_matches:
            param_name = param_match.group(2)
            string_attr = param_match.group(3)
            param_value = param_match.group(4)

            # Determine if value should be treated as string
            is_string = string_attr is not None and string_attr.lower() == "true"

            # Parse parameter values
            args[param_name] = _parse_xml_parameter_value(param_value, is_string)

        # Build OpenAI-format tool_call
        tool_call: ToolCallDict = {
            "id": f"call_{uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(args, sort_keys=True),
            },
        }
        extracted_calls.append(tool_call)
        logger.debug(f" Anthropic XML parsed: {tool_name}")

    return extracted_calls


def _parse_xml_parameter_value(
    value_str: str, is_string: bool
) -> str | int | float | bool | list[Any] | dict[str, Any] | None:
    """Parse XML parameter value"""
    value_str = value_str.strip()

    # If explicitly marked as string, return as string directly
    if is_string:
        return value_str

    # Try parsing as JSON (arrays, objects, booleans, numbers, null, etc.)
    try:
        return cast(
            "str | int | float | bool | list[Any] | dict[str, Any] | None",
            json.loads(value_str),
        )
    except (json.JSONDecodeError, TypeError):
        # Parsing failed; return as plain string
        return value_str
