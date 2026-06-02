"""Minimal ACP agent for end-to-end testing.

Run as a subprocess: python -m tests.acp._mock_acp_agent
Implements the acp.Agent protocol over stdin/stdout, echoing prompts back
with a prefix to verify the full ACP roundtrip.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import acp
from acp.schema import (
    AgentCapabilities,
    CloseSessionResponse,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    NewSessionResponse,
    PromptResponse,
    TextContentBlock,
)


class MockAcpAgent:
    """Echo agent that mirrors prompts back through ACP protocol."""

    def __init__(self) -> None:
        self._conn: object | None = None
        self._sessions: dict[str, str] = {}

    def on_connect(self, conn: object) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: object | None = None,
        client_info: object | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        return InitializeResponse(
            protocol_version=protocol_version,
            agent_capabilities=AgentCapabilities(),
            agent_info=Implementation(name="mock-acp-agent", version="1.0.0"),
        )

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[object] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = cwd
        return NewSessionResponse(session_id=session_id)

    async def load_session(self, cwd: str, session_id: str, **kwargs: Any) -> None:
        return None

    async def list_sessions(self, **kwargs: Any) -> ListSessionsResponse:
        return ListSessionsResponse(sessions=[])

    async def set_session_mode(self, mode_id: str, session_id: str, **kwargs: Any) -> None:
        return None

    async def set_session_model(self, model_id: str, session_id: str, **kwargs: Any) -> None:
        return None

    async def set_config_option(self, config_id: str, session_id: str, value: str | bool, **kwargs: Any) -> None:
        return None

    async def authenticate(self, method_id: str, **kwargs: Any) -> None:
        return None

    async def prompt(
        self,
        prompt: list[TextContentBlock],
        session_id: str,
        message_id: str | None = None,
        **kwargs: Any,
    ) -> PromptResponse:
        text_parts = []
        for block in prompt:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif isinstance(block, dict) and "text" in block:
                text_parts.append(block["text"])
        user_text = " ".join(text_parts)

        if self._conn is not None:
            await self._conn.session_update(
                session_id=session_id,
                update=acp.update_agent_message_text(f"[echo] {user_text}"),
            )

        return PromptResponse(stop_reason="end_turn")

    async def fork_session(self, cwd: str, session_id: str, **kwargs: Any) -> None:
        return None

    async def resume_session(self, cwd: str, session_id: str, **kwargs: Any) -> None:
        return None

    async def close_session(self, session_id: str, **kwargs: Any) -> CloseSessionResponse:
        self._sessions.pop(session_id, None)
        return CloseSessionResponse()

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        pass

    async def ext_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, Any]) -> None:
        pass


async def main() -> None:
    agent = MockAcpAgent()
    await acp.run_agent(agent)


if __name__ == "__main__":
    asyncio.run(main())
