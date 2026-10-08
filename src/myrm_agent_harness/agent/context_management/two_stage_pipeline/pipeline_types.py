"""Strong types and schemas for two-stage context assembly and provider protocol decoupling.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- LlmProviderProtocolKind: Supported LLM provider wire protocol formats.
- LogicalTurn: Provider-agnostic dialogue turn in semantic representation.
- LogicalToolSpec: Provider-agnostic tool definition.
- LogicalContextBundle: Stage 1 Output: Semantic high-level logical context representation.
- ProviderPayloadResult: Stage 2 Output: Wire-ready HTTP/JSON payload formatted for target provider.
- AssemblyAdjustmentDirective: Backchannel feedback directive sent from Stage 2 back to Stage 1 for
  adaptation.
- PipelineStageReceipt: Receipt summarizing end-to-end two-stage transformation integrity.

[POS]
Strong types and schemas for two-stage context assembly and provider protocol decoupling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Union

PrimitiveValue = Union[str, int, float, bool, None]


class LlmProviderProtocolKind(str, Enum):
    """Supported LLM provider wire protocol formats."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"


@dataclass(frozen=True)
class LogicalTurn:
    """Provider-agnostic dialogue turn in semantic representation."""

    turn_id: str
    role: str  # "user", "assistant", "tool", "system"
    content: str
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    reasoning_content: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LogicalToolSpec:
    """Provider-agnostic tool definition."""

    name: str
    description: str
    parameters_schema: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class LogicalContextBundle:
    """Stage 1 Output: Semantic high-level logical context representation."""

    session_id: str
    system_directives: List[str]
    dialogue_turns: List[LogicalTurn]
    active_tools: List[LogicalToolSpec] = field(default_factory=list)
    temperature: float = 0.7
    max_tokens: int = 4096
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderPayloadResult:
    """Stage 2 Output: Wire-ready HTTP/JSON payload formatted for target provider."""

    provider: LlmProviderProtocolKind
    payload_dict: Dict[str, str]  # JSON-serializable wire payload
    estimated_tokens: int
    system_prompt_mode: str  # "top_level_param", "developer_message", "system_instruction"
    payload_hash: str


@dataclass(frozen=True)
class AssemblyAdjustmentDirective:
    """Backchannel feedback directive sent from Stage 2 back to Stage 1 for adaptation."""

    requires_inline_system: bool = False
    strip_reasoning_traces: bool = False
    max_character_clamping: Optional[int] = None
    reason: str = ""


@dataclass(frozen=True)
class PipelineStageReceipt:
    """Receipt summarizing end-to-end two-stage transformation integrity."""

    session_id: str
    target_provider: LlmProviderProtocolKind
    turns_count: int
    tools_count: int
    system_directives_count: int
    wire_payload_bytes: int
    pipeline_hash: str
