"""[POS]: src/myrm_agent_harness/toolkits/memory/tool_backup/models.py
[INPUT]: Core domain primitives and status enumerations for durable tool use backup index.
[OUTPUT]: Strongly typed ToolUseRecord, ToolUseQueryFilter, and ToolUseStats contracts.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ToolUseStatus(StrEnum):
    """Execution outcome status of a recorded tool use."""

    SUCCESS = "success"
    ERROR = "error"


class ToolUseRecord(BaseModel):
    """Durable record representing an exact tool input and output observation."""

    id: str = Field(..., description="Unique identifier of the tool use record")
    session_id: str = Field(..., description="Associated session identifier")
    tool_name: str = Field(..., description="Name of the invoked tool")
    tool_call_id: str = Field(default="", description="Optional LLM tool call reference ID")
    raw_input: str = Field(..., description="Exact raw input string or JSON parameters")
    raw_output: str = Field(..., description="Raw output text or observations")
    status: ToolUseStatus = Field(default=ToolUseStatus.SUCCESS, description="Execution status")
    duration_ms: float = Field(default=0.0, description="Tool execution duration in milliseconds")
    created_at_epoch: float = Field(..., description="Creation epoch timestamp in seconds")
    is_truncated: bool = Field(default=False, description="Whether output was truncated for safety")
    original_output_bytes: int = Field(default=0, description="Original byte length before truncation")
    metadata: dict[str, str] = Field(default_factory=dict, description="Custom contextual metadata tags")


class ToolUseQueryFilter(BaseModel):
    """Filter specifications for auditing and retrieving tool uses."""

    session_id: str | None = Field(default=None, description="Filter by session identifier")
    tool_name: str | None = Field(default=None, description="Filter by specific tool name")
    status: ToolUseStatus | None = Field(default=None, description="Filter by execution outcome")
    limit: int = Field(default=50, ge=1, le=500, description="Maximum number of items to return")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")


class ToolUseStats(BaseModel):
    """Aggregate audit metrics for tool invocations."""

    total_tool_uses: int = Field(default=0, description="Total tool use records counted")
    success_count: int = Field(default=0, description="Count of successful tool executions")
    error_count: int = Field(default=0, description="Count of failed tool executions")
    avg_duration_ms: float = Field(default=0.0, description="Average tool execution duration in ms")
