"""ACP Session ↔ Agent instance bridge.

Maps ACP sessions to agent instances (via AgentProtocol), forwarding
prompts and translating streaming events back to ACP notifications
via the event_translator.


[INPUT]
- acp::Client, session_notification, update_agent_message_text (POS: ACP official SDK)
- myrm_agent_harness.toolkits.acp.server.event_translator::translate_agent_event (POS: AgentEvent → ACP notification translation layer)
- myrm_agent_harness.utils.runtime.cancellation::CancellationToken (POS: cancellation token abstraction)

[OUTPUT]
- AgentProtocol: minimal protocol for Agent instances
- AgentFactory: Agent factory protocol
- AgentBridge: ACP Session ↔ Agent mapping manager

[POS]
ACP Session lifecycle management layer. Handles session-to-agent instance mapping, prompt forwarding,
and event stream translation, bridging the ACP Server and Agent layer.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

from acp import session_notification, update_agent_message_text
from acp.schema import PromptResponse, SessionNotification

from myrm_agent_harness.toolkits.acp.server.event_translator import translate_agent_event

if TYPE_CHECKING:
    from acp import Client

    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

logger = logging.getLogger(__name__)


class AgentProtocol(Protocol):
    """Minimal protocol for agent instances used by ACP bridge.

    Any agent implementing run() with this signature is compatible.
    BaseAgent and SkillAgent satisfy this protocol automatically.
    """

    def run(
        self,
        query: str,
        cancel_token: object | None = None,
        context: dict[str, object] | None = None,
        **kwargs: object,
    ) -> AsyncGenerator[dict[str, object]]:
        """Run the agent and yield streaming events."""
        ...


@runtime_checkable
class AgentFactory(Protocol):
    """Protocol for creating Agent instances from session context.

    Business layer provides the concrete implementation.
    """

    async def create_agent(
        self,
        session_id: str,
        cwd: str,
    ) -> AgentProtocol:
        """Create a configured agent instance for the given session."""
        ...


class _SessionState:
    __slots__ = ("active_tool_calls", "agent", "cancel_token", "cwd", "session_id")

    def __init__(self, session_id: str, agent: AgentProtocol, cwd: str) -> None:
        self.session_id = session_id
        self.agent = agent
        self.cwd = cwd
        self.cancel_token: CancellationToken | None = None
        self.active_tool_calls: set[str] = set()


class AgentBridge:
    """Manages ACP session lifecycle and agent execution.

    Holds session → agent mappings, forwards prompts to agents,
    and streams translated events back to the IDE client.
    """

    def __init__(self, agent_factory: AgentFactory) -> None:
        self._factory = agent_factory
        self._sessions: dict[str, _SessionState] = {}

    async def create_session(self, cwd: str) -> str:
        """Create a new ACP session with a fresh agent instance."""
        session_id = uuid4().hex
        agent = await self._factory.create_agent(session_id, cwd)
        self._sessions[session_id] = _SessionState(session_id, agent, cwd)
        logger.info("acp_session_created session_id=%s cwd=%s", session_id, cwd)
        return session_id

    async def prompt(
        self,
        session_id: str,
        query: str,
        conn: Client,
    ) -> PromptResponse:
        """Execute an agent turn and stream events to the IDE client.

        Args:
            session_id: ACP session to run the prompt in.
            query: User's text query extracted from ACP prompt blocks.
            conn: ACP client connection for sending notifications.

        Returns:
            PromptResponse indicating why the turn ended.
        """
        state = self._sessions.get(session_id)
        if state is None:
            logger.error("acp_prompt_unknown_session session_id=%s", session_id)
            return PromptResponse(stop_reason="end_turn")

        from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

        state.cancel_token = CancellationToken()
        state.active_tool_calls.clear()

        stop_reason: str = "end_turn"

        try:
            async for event in state.agent.run(
                query=query,
                cancel_token=state.cancel_token,
                context={"workspace_path": state.cwd, "session_id": session_id},
            ):
                notification = translate_agent_event(
                    session_id,
                    event,
                    state.active_tool_calls,
                )
                if notification is not None:
                    await _send_notification(conn, notification)

                event_type_str = str(event.get("type", ""))
                if event_type_str == "cancelled":
                    stop_reason = "cancelled"
                elif event_type_str == "error":
                    stop_reason = "end_turn"

        except asyncio.CancelledError:
            stop_reason = "cancelled"
        except Exception as exc:
            logger.exception("acp_prompt_error session_id=%s", session_id)
            error_msg = f"Agent error: {type(exc).__name__}"
            error_notification = _build_error_notification(session_id, error_msg)
            await _send_notification(conn, error_notification)
            stop_reason = "end_turn"
        finally:
            state.cancel_token = None
            state.active_tool_calls.clear()

        return PromptResponse(stop_reason=stop_reason)

    async def cancel(self, session_id: str) -> None:
        """Cancel an in-progress agent turn."""
        state = self._sessions.get(session_id)
        if state and state.cancel_token:
            state.cancel_token.cancel("ACP cancel request")
            logger.info("acp_session_cancelled session_id=%s", session_id)

    def close_session(self, session_id: str) -> None:
        """Remove a session and its associated agent."""
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info("acp_session_closed session_id=%s", session_id)

    def list_sessions(self) -> list[str]:
        """Return active session IDs."""
        return list(self._sessions)

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions


async def _send_notification(conn: Client, notification: SessionNotification) -> None:
    """Send an ACP session notification to the IDE client."""
    try:
        await conn.session_notification(notification)
    except Exception:
        logger.debug("acp_notification_send_failed", exc_info=True)


def _build_error_notification(session_id_val: str, message: str) -> SessionNotification:
    """Build an ACP notification with an error message visible to the user."""
    return session_notification(session_id_val, update_agent_message_text(f"\n\n {message}"))
