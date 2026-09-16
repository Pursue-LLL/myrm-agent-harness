"""Tool call parser module.

Thin compatibility facade: the parsers live in adapters.parsers submodules
(split by model format family); this module keeps the original import paths
stable and hosts the priority-ordered parse_tool_calls() dispatcher.

[INPUT]
- adapters.parsers.openai_format (POS: OpenAI-format tool call parsing)
- adapters.parsers.glm_xml (POS: GLM XML tool call parsing)
- adapters.parsers.qwen_xml_json (POS: Qwen XML JSON tool call parsing)
- adapters.parsers.anthropic_xml (POS: Anthropic XML tool call parsing)
- adapters.parsers.deepseek_inline (POS: DeepSeek inline tool call parsing)
- adapters.parsers.deepseek_dsml (POS: DeepSeek DSML tool call parsing)
- adapters.parsers.leaked_json (POS: leaked raw JSON tool call parsing)

[OUTPUT]
- ToolCallDict, FunctionCallDict: tool call type definitions
- parse_tool_calls(): unified parser for multiple LLM tool call formats
- HTML_ENTITY_RE, decode_html_entities_str(), decode_html_entities_in_args(): xAI/Grok HTML entity decoding

[POS]
Tool call parser facade. Unified handling of tool call formats from multiple LLMs.
Parses by priority: OpenAI standard format, GLM XML, Anthropic XML, Qwen XML JSON, DeepSeek inline, DeepSeek DSML, Leaked raw JSON.
Provides HTML entity decoding (xAI/Grok workaround), called by adapters.converters after args parsing.
As the parser layer, depended on by adapters.converters for cross-model tool call compatibility.
"""

from __future__ import annotations

import logging
from typing import Any

from myrm_agent_harness.toolkits.llms.adapters.parsers.anthropic_xml import (
    _parse_anthropic_xml_format,
    _parse_xml_parameter_value,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.deepseek_dsml import (
    _parse_deepseek_dsml_format,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.deepseek_inline import (
    _parse_deepseek_inline_format,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.glm_xml import (
    _parse_glm_xml_format,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.json_scanner import (
    _find_json_object_end,
    _is_inside_code_block,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.leaked_json import (
    _parse_leaked_json_tool_calls_format,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.openai_format import (
    _parse_openai_format,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.qwen_xml_json import (
    _parse_qwen_xml_json_format,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.text_utils import (
    HTML_ENTITY_RE,
    clean_xml_tool_tags,
    decode_html_entities_in_args,
    decode_html_entities_str,
)
from myrm_agent_harness.toolkits.llms.adapters.parsers.types import (
    FunctionCallDict,
    LLMResponseDict,
    ToolCallDict,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FunctionCallDict",
    "HTML_ENTITY_RE",
    "LLMResponseDict",
    "ToolCallDict",
    "_find_json_object_end",
    "_is_inside_code_block",
    "_parse_anthropic_xml_format",
    "_parse_deepseek_dsml_format",
    "_parse_deepseek_inline_format",
    "_parse_glm_xml_format",
    "_parse_leaked_json_tool_calls_format",
    "_parse_openai_format",
    "_parse_qwen_xml_json_format",
    "_parse_xml_parameter_value",
    "clean_xml_tool_tags",
    "decode_html_entities_in_args",
    "decode_html_entities_str",
    "parse_tool_calls",
]


def parse_tool_calls(
    response_dict: LLMResponseDict | dict[str, Any],
    available_tools: list[str] | None = None,
) -> list[ToolCallDict]:
    """Unified tool call parsing entry point

    Tries parsing tool calls in priority order, returns OpenAI-format tool_calls list.

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
                    " Filtered %d hallucinated tool call(s) not in available_tools: %s",
                    dropped,
                    dropped_names,
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

    # 6. Leaked JSON tool_calls format (e.g. Gemini / Llama raw JSON in text)
    tool_calls = _parse_leaked_json_tool_calls_format(content, available_tools)
    if tool_calls:
        logger.warning(f" Parsed from content {len(tool_calls)} tool calls (Leaked JSON format)")
        return tool_calls

    return []
