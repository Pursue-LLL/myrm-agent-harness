"""DeepSeek DSML tool call parsing.

[INPUT]
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- _parse_deepseek_dsml_format(): DeepSeek DSML tool call parsing.

[POS]
DeepSeek DSML-format tool-call parser.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from typing import Any
from uuid import uuid4

from myrm_agent_harness.toolkits.llms.adapters.parsers.types import LLMResponseDict, ToolCallDict

logger = logging.getLogger(__name__)


def _parse_deepseek_dsml_format(
    response_dict: LLMResponseDict | dict[str, Any],
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Parse DeepSeek DSML format tool calls"""
    content = response_dict.get("content", "") or ""
    reasoning_content = response_dict.get("reasoning_content", "") or ""
    text = content + "\n" + reasoning_content

    if not text or "DSML" not in text:
        return []

    tool_calls: list[ToolCallDict] = []

    block_pattern = re.compile(r"<[｜|]+DSML[｜|]+tool_calls>(.*?)</[｜|]+DSML[｜|]+tool_calls>", re.DOTALL)
    blocks = block_pattern.findall(text)

    if not blocks:
        unclosed_pattern = re.compile(r"<[｜|]+DSML[｜|]+tool_calls>(.*)", re.DOTALL)
        blocks = unclosed_pattern.findall(text)

    for idx, block in enumerate(blocks):
        invoke_pattern = re.compile(
            r'<[｜|]+DSML[｜|]+invoke\s+name=["\']([^"\']+)["\']>(.*?)</[｜|]+DSML[｜|]+invoke>',
            re.DOTALL,
        )
        invokes = invoke_pattern.findall(block)

        if not invokes:
            invoke_pattern_unclosed = re.compile(
                r'<[｜|]+DSML[｜|]+invoke\s+name=["\']([^"\']+)["\']>(.*?)(?:<[｜|]+DSML[｜|]+invoke|$)',
                re.DOTALL,
            )
            invokes = invoke_pattern_unclosed.findall(block)

        for tool_name, params_text in invokes:
            if available_tools and tool_name not in available_tools:
                logger.debug(f" DeepSeek DSML tool call name not in available tools: {tool_name}")
                continue

            args: dict[str, Any] = {}
            param_pattern = re.compile(
                r'<[｜|]+DSML[｜|]+parameter\s+name=["\']([^"\']+)["\']\s+string=["\'](true|false)["\']>(.*?)</[｜|]+DSML[｜|]+parameter>',
                re.DOTALL,
            )
            params = param_pattern.findall(params_text)

            for p_name, is_string, p_value in params:
                val = p_value.strip()
                if is_string.lower() == "false":
                    with contextlib.suppress(json.JSONDecodeError):
                        val = json.loads(val)
                args[p_name] = val

            tool_call: ToolCallDict = {
                "id": f"call_{uuid4().hex[:24]}",
                "index": idx,
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
            tool_calls.append(tool_call)
            logger.debug(f" DeepSeek DSML parsed: {tool_name}")

    return tool_calls
