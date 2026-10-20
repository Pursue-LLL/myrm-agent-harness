"""[INPUT] AgentOwnedExecutionContext and operational request parameters.
[OUTPUT] AgentOwnedOperationsFabric coordinator managing isolated contexts and list rosters.
[POS] Coordination fabric for Agent-Owned operations isolation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

from .types import (
    AgentOwnedExecutionContext,
    AgentRosterEntry,
    AgentScopedError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AgentOwnedOperationsFabric:
    """Coordinator ensuring multi-agent operations remain strictly agent-owned.

    Prevents global state pollution by confining provider configs, capability resolution,
    allowlists, and failure stacks directly inside each agent's execution context.
    """

    def __init__(self) -> None:
        self._contexts: dict[str, AgentOwnedExecutionContext] = {}

    def register_agent(self, context: AgentOwnedExecutionContext) -> None:
        """Register or update an agent-owned execution context."""
        self._contexts[context.agent_id] = context
        logger.debug(
            "Registered agent-owned context for %s (%s)",
            context.agent_id,
            context.provider_config.model_name,
        )

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent instance when its lifecycle terminates."""
        if agent_id in self._contexts:
            del self._contexts[agent_id]
            return True
        return False

    def get_agent(self, agent_id: str) -> AgentOwnedExecutionContext | None:
        """Retrieve an agent context by ID."""
        return self._contexts.get(agent_id)

    def resolve_capability(self, agent_id: str, target_capability: str) -> bool:
        """Resolve whether target capability is permitted under the agent's owned allowlist.

        Returns False if the agent does not exist or if the capability is not permitted.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning("Attempted capability resolution for unregistered agent %s", agent_id)
            return False
        return agent.resolve_capability(target_capability)

    def record_agent_error(
        self,
        agent_id: str,
        operation: str,
        error_type: str,
        message: str,
        fatal: bool = False,
        context: dict[str, str] | None = None,
    ) -> AgentScopedError:
        """Record an operation failure strictly within the agent-owned stack."""
        agent = self.get_agent(agent_id)
        if not agent:
            # Fallback isolated stub error
            return AgentScopedError(
                agent_id=agent_id,
                operation=operation,
                error_type=error_type,
                message=f"[Unregistered Agent] {message}",
                fatal=fatal,
                context=context or {},
            )
        return agent.record_error(
            operation=operation,
            error_type=error_type,
            message=message,
            fatal=fatal,
            context=context,
        )

    def get_agent_errors(self, agent_id: str) -> list[AgentScopedError]:
        """Fetch all isolated errors recorded under the specific agent."""
        agent = self.get_agent(agent_id)
        if not agent:
            return []
        return list(agent.error_stack)

    def clear_agent_errors(self, agent_id: str) -> None:
        """Clear errors for a specific agent without affecting others."""
        agent = self.get_agent(agent_id)
        if agent:
            agent.clear_errors()

    def get_roster(self, session_id: str | None = None) -> list[AgentRosterEntry]:
        """Export standardized list-form roster of registered agents.

        If session_id is provided, filters to agents attached to that session.
        """
        entries: list[AgentRosterEntry] = []
        for ctx in self._contexts.values():
            if session_id is None or ctx.session_id == session_id:
                entries.append(ctx.to_roster_entry())
        # Sort stably by agent_id
        entries.sort(key=lambda item: item.agent_id)
        return entries

    def execute_isolated_operation(
        self,
        agent_id: str,
        operation_name: str,
        fn: Callable[[], T],
        fatal_on_exception: bool = False,
    ) -> T | None:
        """Execute an operation within an agent-owned sandbox.

        Catches any exception, records it directly into the agent's isolated error stack,
        and returns None rather than propagating the error to the global orchestrator.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            self.record_agent_error(
                agent_id=agent_id,
                operation=operation_name,
                error_type="AgentNotFoundError",
                message=f"Agent {agent_id} is not registered in operations fabric",
                fatal=True,
            )
            return None

        try:
            return fn()
        except Exception as exc:
            agent.record_error(
                operation=operation_name,
                error_type=exc.__class__.__name__,
                message=str(exc),
                fatal=fatal_on_exception,
            )
            logger.info(
                "Isolated error intercepted for agent %s in %s: %s",
                agent_id,
                operation_name,
                exc,
            )
            return None
