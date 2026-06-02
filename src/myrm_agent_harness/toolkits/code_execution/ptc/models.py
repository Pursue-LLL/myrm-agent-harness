"""PTC data models.

[INPUT]
- pydantic (POS: Data validation and settings management)

[OUTPUT]
- PtcConfig: PTC execution configuration
- PtcRpcRequest: RPC request from stub to server
- PtcRpcResponse: RPC response from server to stub
- PtcToolCallRecord: Single tool call record for tracing
- PtcExecutionTrace: Complete execution trace for observability

[POS]
Pydantic models for Programmatic Tool Calling. Defines the RPC protocol,
configuration, and observability data structures.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PtcConfig(BaseModel):
    """PTC execution configuration."""

    max_tool_calls: int = Field(default=50, ge=1, le=200)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    max_stdout_bytes: int = Field(default=50_000, ge=1024)
    max_stderr_bytes: int = Field(default=10_000, ge=1024)
    use_project_mode: bool = Field(default=True)
    workspace_path: str | None = Field(default=None)
    venv_path: str | None = Field(default=None)


class PtcRpcRequest(BaseModel):
    """RPC request sent from stub to server."""

    tool: str
    args: dict[str, object]


class PtcRpcResponse(BaseModel):
    """RPC response sent from server to stub."""

    result: str | None = None
    error: str | None = None


class PtcToolCallRecord(BaseModel):
    """Single tool call record for observability."""

    tool: str
    args_preview: str = Field(max_length=120)
    duration_ms: float
    success: bool
    error: str | None = None


class PtcExecutionTrace(BaseModel):
    """Complete PTC execution trace for event_log."""

    script_preview: str = Field(max_length=500)
    tool_calls: list[PtcToolCallRecord] = Field(default_factory=list)
    total_duration_ms: float = 0.0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    exit_code: int | None = None
    killed_reason: str | None = None
