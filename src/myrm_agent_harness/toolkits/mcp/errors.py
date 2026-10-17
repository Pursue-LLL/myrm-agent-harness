"""MCP error-handling types.

[INPUT]
- (none)

[OUTPUT]
- MCPRuntimePostureError: Raised when runtime surface scan blocks MCP tool registration.

[POS]
MCP-specific error types. `reraise_if_cancelled` stays out of here: `utils.runtime.cancellation` owns the
cancellation rule because both `toolkits.mcp` and `agent.middlewares` consume it, and a rule shared by two packages
cannot be hosted by either. Only types that are MCP's own belong in this module.
"""

from __future__ import annotations


class MCPRuntimePostureError(RuntimeError):
    """Runtime MCP instructions/tool descriptions failed security posture."""

    def __init__(self, message: str, *, server_name: str) -> None:
        super().__init__(message)
        self.server_name = server_name
