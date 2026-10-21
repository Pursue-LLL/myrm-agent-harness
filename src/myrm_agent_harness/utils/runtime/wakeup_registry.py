"""Global registry for async wakeup events (Idle Wakeup).

Provides a decoupling mechanism for the Harness framework to notify
the Server layer when an asynchronous background subagent completes.

[INPUT]
- agent.sub_agents.types::SubAgentResult (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- AsyncWakeupHandler: Protocol for handling asynchronous wakeup events from bac...
- set_global_wakeup_handler: Register a global handler for async wakeup events.
- get_global_wakeup_handler: Retrieve the registered global wakeup handler.

[POS]
Global registry for async wakeup events (Idle Wakeup).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from myrm_agent_harness.agent.sub_agents.types import SubAgentResult


class AsyncWakeupHandler(Protocol):
    """Protocol for handling asynchronous wakeup events from background subagents."""

    async def on_async_wakeup(self, result: SubAgentResult, agent_id: str, session_id: str | None) -> None:
        """Called when an async background subagent completes.

        Args:
            result: The result of the subagent execution.
            agent_id: The ID of the parent agent that spawned the subagent.
            session_id: The session/chat ID to resume (if any).
        """
        ...


_global_wakeup_handler: AsyncWakeupHandler | None = None


def set_global_wakeup_handler(handler: AsyncWakeupHandler | None) -> None:
    """Register a global handler for async wakeup events."""
    global _global_wakeup_handler
    _global_wakeup_handler = handler


def get_global_wakeup_handler() -> AsyncWakeupHandler | None:
    """Retrieve the registered global wakeup handler."""
    return _global_wakeup_handler
