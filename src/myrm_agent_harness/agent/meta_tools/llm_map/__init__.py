"""``llm_map`` agent tool package.

[INPUT]
- .llm_map_tool::create_llm_map_tool, LlmMapInput, TOOL_NAME

[OUTPUT]
- create_llm_map_tool / LlmMapInput / TOOL_NAME: the GUI-facing batch LLM-map tool

[POS]
``llm_map`` agent tool package. Agent-layer adapter over the pure
``toolkits.llms.batch`` fan-out engine.
"""

from .llm_map_tool import TOOL_NAME, LlmMapInput, create_llm_map_tool

__all__ = ["TOOL_NAME", "LlmMapInput", "create_llm_map_tool"]
