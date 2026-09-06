"""A2A protocol boundary contracts.

Defines the Protocol interfaces that business layers implement to
provide AgentCard content and handle A2A task lifecycle.

[INPUT]
- types::AgentCard, types::A2ATask

[OUTPUT]
- AgentCardProvider: Protocol for generating AgentCard
- A2ATaskService: Protocol for handling inbound A2A tasks

[POS]
Framework-business boundary. Harness defines the interface,
server layer implements it with business logic and execution services.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.a2a.types import A2ATask, AgentCard


@runtime_checkable
class AgentCardProvider(Protocol):
    """Generates AgentCard content from business data.

    Business layer implements this to fill AgentCard from
    agent configuration and installed skills.
    """

    async def get_card(self, agent_id: str | None = None) -> AgentCard:
        """Return the public AgentCard for discovery."""
        ...

    async def get_extended_card(self, agent_id: str | None = None) -> AgentCard | None:
        """Return authenticated-only extended card.

        Returns None if not supported (default for single-user scenarios).
        """
        ...


@runtime_checkable
class A2ATaskService(Protocol):
    """Service interface for managing inbound A2A tasks."""

    async def send_task(
        self,
        prompt: str,
        *,
        task_id: str | None = None,
        agent_id: str | None = None,
        push_url: str | None = None,
        push_secret: str | None = None,
    ) -> A2ATask:
        """Enqueue a new A2A task and return initial state."""
        ...

    async def get_task(self, task_id: str) -> A2ATask | None:
        """Retrieve task state and artifacts by ID."""
        ...

    async def cancel_task(self, task_id: str) -> bool:
        """Request cancellation of an active task."""
        ...
