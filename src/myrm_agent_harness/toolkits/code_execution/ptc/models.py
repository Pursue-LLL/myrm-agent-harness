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
    max_output_chars: int = Field(
        default=200_000,
        ge=1024,
        description=(
            "Single hard ceiling for both stdout and stderr of one execution. "
            "Defaults to the shared MAX_OUTPUT_CHARS so every executor applies the "
            "same number; a second, different budget would make the visible result "
            "depend on which layer truncated first."
        ),
    )


class PtcRpcRequest(BaseModel):
    """RPC request sent from stub to server."""

    tool: str
    args: dict[str, object]
    auth_token: str | None = None
    """Per-process bearer token minted by the server; required for dispatch."""


class PtcRpcResponse(BaseModel):
    """RPC response sent from server to stub.

    ``result`` carries the tool's native return value. Dicts/lists stay structured
    on the wire (JSON-native payload) so orchestration primitives that declare
    ``-> dict`` reach scripts as dicts; strings stay flat strings.
    """

    result: object | None = None
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
