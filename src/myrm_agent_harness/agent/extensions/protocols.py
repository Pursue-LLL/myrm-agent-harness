"""[INPUT]
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)

[OUTPUT]
- AgentExtension: Protocol for Agent Extensions.

[POS]
Provides AgentExtension.
"""

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.base_agent import BaseAgent


@runtime_checkable
class AgentExtension(Protocol):
    """Protocol for Agent Extensions.

    Extensions encapsulate high-cohesion functionality (Tools, Middlewares,
    Lifecycles) into a single pluggable component. This allows Server-layer
    business logic to be cleanly injected into the Harness layer without
    violating architectural boundaries.
    """

    @property
    def name(self) -> str:
        """Name of the extension for logging and uniqueness."""
        ...

    async def on_agent_init(self, agent: "BaseAgent") -> None:
        """Hook called during ``_ensure_initialized``, before the first ``create_agent``.

        Register dynamic tools on ``agent._tool_registry`` (or call ``agent.add_tools`` during
        this phase). ``BaseAgent`` resolves the registry once, then builds the agent graph a
        single time. Do not assume ``agent._agent`` exists yet.
        """
        ...

    async def on_agent_shutdown(self, agent: "BaseAgent") -> None:
        """Hook called when the agent is being cleaned up.

        Use this to release resources, flush metrics, etc.
        """
        ...

    def get_tools(self) -> list["BaseTool"] | None:
        """Provide static tools registered before ``on_agent_init``."""
        ...

    def get_middlewares(self) -> list["AgentMiddleware[Any, Any]"] | None:
        """Provide a list of middlewares to inject into the agent."""
        ...
