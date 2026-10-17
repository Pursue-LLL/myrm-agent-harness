"""MCP error-handling types.

[INPUT]
- (none)

[OUTPUT]
- MCPRuntimePostureError: Raised when runtime surface scan blocks MCP tool registration.

[POS]
MCP-specific error types. The task-cancellation rule (`utils.runtime.cancellation.reraise_if_cancelled`) is not one of
them: both `toolkits` and `agent` consume it, so hosting it in this consumer made `agent.middlewares` import across
the layer. Only types that are MCP's own belong here.
"""

from __future__ import annotations


class MCPRuntimePostureError(RuntimeError):
    """Runtime MCP instructions/tool descriptions failed security posture."""

    def __init__(self, message: str, *, server_name: str) -> None:
        super().__init__(message)
        self.server_name = server_name
