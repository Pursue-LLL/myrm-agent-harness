"""Agent execution errors.

[INPUT]
- (none)

[OUTPUT]
- AgentBusyError: Raised when attempting to run an agent that is already running.
- ToolStuckException: Raised when an agent gets stuck in an unproductive loop (e.g. repeated tool failures).
- RunawayCircuitBreakException: Raised when an unattended agent trips circuit breaker on runaway loops.

[POS]
Agent execution errors.
"""


class AgentBusyError(Exception):
    """Raised when attempting to run an agent that is already running."""

    pass


class ToolStuckException(Exception):  # noqa: N818  intentional descriptive name (public API, cross-repo)
    """Raised when an agent gets stuck in an unproductive loop (e.g. repeated tool failures)."""

    pass


class RunawayCircuitBreakException(Exception):  # noqa: N818
    """Raised when an unattended agent triggers circuit-breaker due to persistent runaway loops or identical failures."""

    def __init__(
        self,
        message: str,
        *,
        loop_kind: str | None = None,
        tool_name: str | None = None,
        consecutive_count: int = 0,
        signature_hash: str | None = None,
    ) -> None:
        super().__init__(message)
        self.loop_kind = loop_kind
        self.tool_name = tool_name
        self.consecutive_count = consecutive_count
        self.signature_hash = signature_hash

