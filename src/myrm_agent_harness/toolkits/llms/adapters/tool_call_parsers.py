"""Tool call parser module


[INPUT]
- json::json (POS: Python JSON library)
- re::re (POS: Python regex library)
- uuid::uuid4 (POS: UUID generator)

[OUTPUT]
- ToolCallDict, FunctionCallDict: tool call type definitions
- parse_tool_calls(): unified parser for multiple LLM tool call formats
- HTML_ENTITY_RE, decode_html_entities_str(), decode_html_entities_in_args(): xAI/Grok HTML entity decoding

[POS]
Tool call parser module. Unified handling of tool call formats from multiple LLMs.
Parses by priority: OpenAI standard format, GLM XML, Anthropic XML, DeepSeek inline.
Provides HTML entity decoding (xAI/Grok workaround), called by adapters.converters after args parsing.
As the parser layer, depended on by adapters.converters for cross-model tool call compatibility.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from typing import Any, Literal, TypedDict
from uuid import uuid4

logger = logging.getLogger(__name__)


# ============================================================================
# Type Definitions
# ============================================================================


class FunctionCallDict(TypedDict):
    """OpenAI-format function call"""

    name: str
    arguments: str  # JSON string


class _ToolCallDictRequired(TypedDict):
    """Tool call required fields"""

    id: str
    type: Literal["function"]
    function: FunctionCallDict


class ToolCallDict(_ToolCallDictRequired, total=False):
    """OpenAI-format tool call

    Required fields: id, type, function
    Optional field: index (For streaming responses)
    """

    index: int


class LLMResponseDict(TypedDict, total=False):
    """LLM response dict"""

    content: str
    role: str
    tool_calls: list[ToolCallDict]
    function_call: FunctionCallDict
    reasoning_content: str  # GLM model reasoning content


def parse_tool_calls(
    response_dict: LLMResponseDict | dict[str, Any],
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Unified tool call parsing entry point

    Tries parsing tool calls in priority order, returns OpenAI-format tool_calls list。

    Args:
        response_dict: LLM response dict, containing content, tool_calls, reasoning_content, etc.
        available_tools: Available tool name list for inline format parsing

    Returns:
        OpenAI-format tool_calls list, empty list if no tool calls parsed
    """
    # 1. Standard OpenAI format
    tool_calls = _parse_openai_format(response_dict)
    if tool_calls:
        if available_tools:
            filtered = [tc for tc in tool_calls if tc.get("function", {}).get("name") in available_tools]
            dropped = len(tool_calls) - len(filtered)
            if dropped:
                dropped_names = [tc.get("function", {}).get("name") for tc in tool_calls if tc not in filtered]
                logger.warning(
                    " Filtered %d hallucinated tool call(s) not in available_tools: %s", dropped, dropped_names
                )
            if filtered:
                return filtered
        else:
            return tool_calls

    # 2. GLM XML format (reasoning_content tool_call tags in)
    reasoning_content = response_dict.get("reasoning_content", "")
    tool_calls = _parse_glm_xml_format(reasoning_content)
    if tool_calls:
        logger.warning(f" Parsed from reasoning_content {len(tool_calls)} tool calls (GLM XML format)")
        return tool_calls

    # 3. Anthropic XML format (content invoke tags in)
    content = response_dict.get("content", "")
    tool_calls = _parse_anthropic_xml_format(content, available_tools)
    if tool_calls:
        logger.warning(f" Parsed from content {len(tool_calls)} tool calls (Anthropic XML format)")
        return tool_calls

    # 3.5 Qwen XML JSON format
    tool_calls = _parse_qwen_xml_json_format(content, available_tools)
    if tool_calls:
        logger.warning(f" Parsed from content {len(tool_calls)} tool calls (Qwen XML JSON format)")
        return tool_calls

    # 4. DeepSeek inline format
    tool_calls = _parse_deepseek_inline_format(content, available_tools)
    if tool_calls:
        logger.warning(f" Parsed from content {len(tool_calls)} tool calls (DeepSeek inline format)")
        return tool_calls

    # 5. DeepSeek DSML format
    tool_calls = _parse_deepseek_dsml_format(response_dict, available_tools)
    if tool_calls:
        logger.warning(f" Parsed {len(tool_calls)} tool calls (DeepSeek DSML format)")
        return tool_calls

    return []


def _parse_openai_format(response_dict: LLMResponseDict | dict[str, Any]) -> list[ToolCallDict]:
    """Parse standard OpenAI-format tool call"""
    raw_tool_calls = response_dict.get("tool_calls")
    if not raw_tool_calls or not isinstance(raw_tool_calls, list):
        return []

    # Append UUID suffix to each tool_call_id for global uniqueness, preventing model ID reuse errors
    for tc in raw_tool_calls:
        if "id" in tc and isinstance(tc["id"], str):
            original_id = tc["id"]
            if "_vtx" not in original_id:
                tc["id"] = f"{original_id}_vtx{uuid4().hex[:4]}"

    return raw_tool_calls  # type: ignore[return-value]


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
) -> str | int | float | bool | list[Any] | dict[str, Any]:
    """Parse XML parameter value"""
    value_str = value_str.strip()

    # If explicitly marked as string, return as string directly
    if is_string:
        return value_str

    # Try parsing as JSON (arrays, objects, booleans, numbers, etc.)
    try:
        return json.loads(value_str)
    except (json.JSONDecodeError, TypeError):
        # Parsing failed，Return as plain string
        return value_str


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
            r'<[｜|]+DSML[｜|]+invoke\s+name=["\']([^"\']+)["\']>(.*?)</[｜|]+DSML[｜|]+invoke>', re.DOTALL
        )
        invokes = invoke_pattern.findall(block)

        if not invokes:
            invoke_pattern_unclosed = re.compile(
                r'<[｜|]+DSML[｜|]+invoke\s+name=["\']([^"\']+)["\']>(.*?)(?:<[｜|]+DSML[｜|]+invoke|$)', re.DOTALL
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
                "function": {"name": tool_name, "arguments": json.dumps(args, ensure_ascii=False)},
            }
            tool_calls.append(tool_call)
            logger.debug(f" DeepSeek DSML parsed: {tool_name}")

    return tool_calls


# ============================================================================
# XML Tool Tag Cleaner
# ============================================================================

_DSML_PATTERN = re.compile(r"<[｜|]+DSML[｜|]+tool_calls>.*?</[｜|]+DSML[｜|]+tool_calls>", re.DOTALL)
_DSML_UNCLOSED_PATTERN = re.compile(r"<[｜|]+DSML[｜|]+tool_calls>.*", re.DOTALL)
_XML_TOOL_PATTERN = re.compile(
    r"<(tool_call|invoke(?:\s+name=[\"'][^\"']*[\"'])?)>.*?</(?:\1|invoke)>",
    re.DOTALL,
)
_XML_TOOL_UNCLOSED_PATTERN = re.compile(r"<(tool_call|invoke(?:\s+name=[\"'][^\"']*[\"'])?)>.*", re.DOTALL)
_FUNCTION_CALLS_PATTERN = re.compile(
    r"<(?:antml:)?(?:function|tool)_calls>.*?</(?:antml:)?(?:function|tool)_calls>",
    re.DOTALL,
)


def clean_xml_tool_tags(text: str) -> str:
    """Strip leaked XML tool call tags from text content.

    Handles DSML fullwidth-pipe format, standard invoke/tool_call tags,
    and function_calls/tool_calls wrapper tags. Supports both closed
    and unclosed (truncated) variants.
    """
    if not text:
        return text
    text = _FUNCTION_CALLS_PATTERN.sub("", text)
    text = _DSML_PATTERN.sub("", text)
    text = _DSML_UNCLOSED_PATTERN.sub("", text)
    text = _XML_TOOL_PATTERN.sub("", text)
    text = _XML_TOOL_UNCLOSED_PATTERN.sub("", text)
    return text.strip()


# ============================================================================
# HTML Entity Decoder (xAI/Grok workaround)
# ============================================================================

HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|#39|#x[0-9a-fA-F]+|#\d+);")


def decode_html_entities_str(value: str) -> str:
    """Decode HTML entities in a single string value."""
    return (
        value.replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&apos;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )


def decode_html_entities_in_args(
    obj: str | int | float | bool | list[Any] | dict[str, Any] | None,
) -> str | int | float | bool | list[Any] | dict[str, Any] | None:
    """Recursively decode HTML entities in tool call arguments.

    xAI/Grok models encode special characters as HTML entities in tool call
    arguments (e.g. ``&&`` becomes ``&amp;&amp;``). This corrupts bash commands
    and other string values. This function recursively walks the parsed args
    and decodes all string values containing HTML entities.

    Safe for non-xAI models: strings without entities pass through unchanged.
    """
    if isinstance(obj, str):
        return decode_html_entities_str(obj) if HTML_ENTITY_RE.search(obj) else obj
    if isinstance(obj, list):
        return [decode_html_entities_in_args(item) for item in obj]
    if isinstance(obj, dict):
        return {k: decode_html_entities_in_args(v) for k, v in obj.items()}
    return obj


def _is_inside_code_block(content: str, position: int) -> bool:
    """Check if a given position is inside a Markdown code block"""
    before = content[:position]
    triple_backticks = before.count("```")
    return triple_backticks % 2 == 1


def _find_json_object_end(text: str) -> int:
    """Find the end position of a JSON object

    Args:
        text: Text starting with '{'

    Returns:
        JSON object end position (inclusive of '}'), or -1 if not found
    """
    if not text.startswith("{"):
        return -1

    depth = 0
    in_string = False
    escape_next = False

    for i, char in enumerate(text):
        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return i + 1

    return -1
