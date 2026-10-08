"""Types and schemas for HITL Denial Events and Tool Result Generation."""

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class DenialResolutionPolicy(StrEnum):
    """Action policy when all tool calls in a reasoning step are denied."""

    STOP = "stop"
    CONTINUE = "continue"


class ToolDenialItem(BaseModel):
    """Specification of a denied tool call."""

    model_config = ConfigDict(frozen=True)

    tool_call_id: str = Field(
        ..., description="Unique ID of the tool call rejected by user"
    )
    tool_name: str = Field(..., description="Name of the tool rejected")
    reason: str = Field(
        default="Operation rejected by user",
        description="Rejection reason or policy note",
    )
    custom_feedback: str | None = Field(
        default=None, description="Optional custom instruction from user"
    )


class SyntheticToolResultBlock(BaseModel):
    """Synthetic ToolResult block created to answer denied tool calls for LLM context."""

    model_config = ConfigDict(frozen=True)

    tool_call_id: str
    tool_name: str
    output: str
    is_error: bool = True
    metadata: dict[str, str] = Field(default_factory=dict)


class ProcessDenialsResult(BaseModel):
    """Result of processing a set of tool denials within a reasoning step."""

    model_config = ConfigDict(frozen=True)

    all_tools_denied: bool
    total_requested: int
    total_denied: int
    resolution_action: DenialResolutionPolicy
    synthetic_results: list[SyntheticToolResultBlock]
    stop_requested: bool
