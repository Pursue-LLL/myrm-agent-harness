"""Tool-call format parsers.

[INPUT]
- adapters.parsers.types (POS: tool-call type definitions)

[OUTPUT]
- Re-exports the full tool_call_parsers public surface: parse_tool_calls(),
  format parsers, text utilities, and type definitions.

[POS]
Tool-call parser package index. Single import surface for all tool-call formats.
"""

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
]
