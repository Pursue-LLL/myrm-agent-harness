"""LLM layer: LangChain , messageconverts, handles, toolcallsparse, Schema normalize"""

from myrm_agent_harness.toolkits.llms.adapters.chat_model import ChatLiteLLM, clean_model_kwargs
from myrm_agent_harness.toolkits.llms.adapters.converters import (
    convert_dict_to_message,
    convert_message_to_dict,
    create_usage_metadata,
)
from myrm_agent_harness.toolkits.llms.adapters.model_capability import ModelCapabilityDetector
from myrm_agent_harness.toolkits.llms.adapters.schema_normalizer import normalize_tool_schema
from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import (
    HTML_ENTITY_RE,
    FunctionCallDict,
    LLMResponseDict,
    ToolCallDict,
    clean_xml_tool_tags,
    decode_html_entities_in_args,
    decode_html_entities_str,
    parse_tool_calls,
)

__all__ = [
    "HTML_ENTITY_RE",
    "ChatLiteLLM",
    "FunctionCallDict",
    "LLMResponseDict",
    "ModelCapabilityDetector",
    "ToolCallDict",
    "clean_model_kwargs",
    "clean_xml_tool_tags",
    "convert_dict_to_message",
    "convert_message_to_dict",
    "create_usage_metadata",
    "decode_html_entities_in_args",
    "decode_html_entities_str",
    "normalize_tool_schema",
    "parse_tool_calls",
]
