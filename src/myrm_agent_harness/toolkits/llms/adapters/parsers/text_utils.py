"""XML tag cleaning and HTML entity decoding for tool-call text.

[INPUT]
- logging (POS: Python logging)
- re (POS: Python regex library)

[OUTPUT]
- clean_xml_tool_tags(): strip leaked XML/JSON tool call tags.
- HTML_ENTITY_RE, decode_html_entities_str(), decode_html_entities_in_args(): xAI/Grok HTML entity decoding.

[POS]
Text utilities for tool-call content cleanup.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)
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
_LEAKED_JSON_TOOL_CALLS_PATTERN = re.compile(
    r"```(?:json)?\s*\{\s*\"tool_calls\"\s*:\s*\[[\s\S]*?\]\s*\}\s*```|\{\s*\"tool_calls\"\s*:\s*\[[\s\S]*?\]\s*\}",
    re.IGNORECASE,
)
HTML_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|#39|#x[0-9a-fA-F]+|#\d+);")


def clean_xml_tool_tags(text: str) -> str:
    """Strip leaked XML and raw JSON tool call tags from text content.

    Handles DSML fullwidth-pipe format, standard invoke/tool_call tags,
    function_calls/tool_calls wrapper tags, and leaked raw JSON tool_calls blocks.
    Supports both closed and unclosed (truncated) variants.
    """
    if not text:
        return text
    text = _FUNCTION_CALLS_PATTERN.sub("", text)
    text = _LEAKED_JSON_TOOL_CALLS_PATTERN.sub("", text)
    text = _DSML_PATTERN.sub("", text)
    text = _DSML_UNCLOSED_PATTERN.sub("", text)
    text = _XML_TOOL_PATTERN.sub("", text)
    text = _XML_TOOL_UNCLOSED_PATTERN.sub("", text)
    return text.strip()


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
