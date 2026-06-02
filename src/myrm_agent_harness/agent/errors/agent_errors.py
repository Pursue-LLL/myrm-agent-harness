"""Agent execution errors.

[INPUT]
- (none)

[OUTPUT]
- AgentBusyError: Raised when attempting to run an agent that is already ru...
- ToolStuckException: Raised when an agent gets stuck in an unproductive loop (...

[POS]
Agent execution errors.
"""


class AgentBusyError(Exception):
    """Raised when attempting to run an agent that is already running."""

    pass


class ToolStuckException(Exception):  # noqa: N818  intentional descriptive name (public API, cross-repo)
    """Raised when an agent gets stuck in an unproductive loop (e.g. repeated tool failures)."""

    pass
