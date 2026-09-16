"""Tool-call type definitions.

[INPUT]
- typing (POS: Python type hints)

[OUTPUT]
- FunctionCallDict, ToolCallDict, LLMResponseDict: wire type definitions.

[POS]
Shared tool-call types used by every format parser and the dispatcher.
"""

from __future__ import annotations

from typing import Literal, TypedDict


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
