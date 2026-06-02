"""ACP Server — implements the Agent Client Protocol interface.

Uses the official Python ACP SDK. This module is the protocol layer:
it handles JSON-RPC methods and delegates actual agent execution to
the AgentBridge.


[INPUT]
- acp::Client, run_agent (POS: ACP official SDK)
- myrm_agent_harness.toolkits.acp.server.bridge::AgentBridge, AgentFactory (POS: ACP session-to-agent mapping layer)

[OUTPUT]
- MyrmAcpServer: ACP server implementation providing the acp.Agent Protocol interface

[POS]
ACP protocol layer. Implements the ACP JSON-RPC protocol spec, translating IDE client requests
into agent execution calls and delegating to AgentBridge for session management.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from acp import PROTOCOL_VERSION, Client, run_agent
from acp.schema import (
    AgentCapabilities,
    AudioContentBlock,
    CloseSessionResponse,
    EmbeddedResourceContentBlock,
    ForkSessionResponse,
    ImageContentBlock,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    NewSessionResponse,
    PromptResponse,
    ResourceContentBlock,
    ResumeSessionResponse,
    SessionInfo,
    SetSessionConfigOptionResponse,
    SetSessionModelResponse,
    SetSessionModeResponse,
    TextContentBlock,
)

from myrm_agent_harness.toolkits.acp.server.bridge import AgentBridge, AgentFactory

if TYPE_CHECKING:
    from acp.schema import (
        ClientCapabilities,
        HttpMcpServer,
        McpServerStdio,
        SseMcpServer,
    )

logger = logging.getLogger(__name__)

_AGENT_NAME = "myrm-agent"
_AGENT_VERSION = "0.1.0"

_ContentBlock = (
    TextContentBlock | ImageContentBlock | AudioContentBlock | ResourceContentBlock | EmbeddedResourceContentBlock
)


class MyrmAcpServer:
    """ACP-compliant agent server backed by myrm-agent-harness.

    Implements the ``acp.Agent`` Protocol, delegating session and
    execution management to :class:`AgentBridge`.
    """

    def __init__(self, agent_factory: AgentFactory) -> None:
        self._bridge = AgentBridge(agent_factory)
        self._conn: Client | None = None

    def on_connect(self, conn: Client) -> None:
        self._conn = conn

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: object,
    ) -> InitializeResponse:
        client_name = client_info.name if client_info else "unknown"
        logger.info("acp_initialize client=%s protocol_version=%d", client_name, protocol_version)

        return InitializeResponse(
            protocol_version=min(protocol_version, PROTOCOL_VERSION),
            agent_info=Implementation(name=_AGENT_NAME, version=_AGENT_VERSION),
            agent_capabilities=AgentCapabilities(),
        )

    async def new_session(
        self,
        cwd: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: object,
    ) -> NewSessionResponse:
        session_id = await self._bridge.create_session(cwd)
        return NewSessionResponse(session_id=session_id)

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: object,
    ) -> LoadSessionResponse | None:
        if self._bridge.has_session(session_id):
            return LoadSessionResponse()
        return None

    async def list_sessions(
        self,
        cursor: str | None = None,
        cwd: str | None = None,
        **kwargs: object,
    ) -> ListSessionsResponse:
        session_ids = self._bridge.list_sessions()
        sessions = [SessionInfo(session_id=sid, cwd=cwd or ".", title=f"Session {sid[:8]}") for sid in session_ids]
        return ListSessionsResponse(sessions=sessions)

    async def prompt(
        self,
        prompt: list[_ContentBlock],
        session_id: str,
        message_id: str | None = None,
        **kwargs: object,
    ) -> PromptResponse:
        query_text = _extract_text(prompt)
        if not query_text:
            return PromptResponse(stop_reason="end_turn")

        if self._conn is None:
            logger.error("acp_prompt_no_connection session_id=%s", session_id)
            return PromptResponse(stop_reason="end_turn")

        return await self._bridge.prompt(session_id, query_text, self._conn)

    async def cancel(self, session_id: str, **kwargs: object) -> None:
        await self._bridge.cancel(session_id)

    async def close_session(self, session_id: str, **kwargs: object) -> CloseSessionResponse | None:
        self._bridge.close_session(session_id)
        return CloseSessionResponse()

    async def set_session_mode(
        self,
        mode_id: str,
        session_id: str,
        **kwargs: object,
    ) -> SetSessionModeResponse | None:
        return None

    async def set_session_model(
        self,
        model_id: str,
        session_id: str,
        **kwargs: object,
    ) -> SetSessionModelResponse | None:
        return None

    async def set_config_option(
        self,
        config_id: str,
        session_id: str,
        value: str | bool,
        **kwargs: object,
    ) -> SetSessionConfigOptionResponse | None:
        return None

    async def authenticate(self, method_id: str, **kwargs: object) -> None:
        return None

    async def fork_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: object,
    ) -> ForkSessionResponse:
        new_session_id = await self._bridge.create_session(cwd)
        return ForkSessionResponse(session_id=new_session_id)

    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[HttpMcpServer | SseMcpServer | McpServerStdio] | None = None,
        **kwargs: object,
    ) -> ResumeSessionResponse:
        if not self._bridge.has_session(session_id):
            await self._bridge.create_session(cwd)
        return ResumeSessionResponse()

    async def ext_method(self, method: str, params: dict[str, object]) -> dict[str, object]:
        return {}

    async def ext_notification(self, method: str, params: dict[str, object]) -> None:
        pass


def _extract_text(prompt_blocks: list[_ContentBlock]) -> str:
    """Extract concatenated text from ACP prompt content blocks."""
    parts: list[str] = []
    for block in prompt_blocks:
        if isinstance(block, TextContentBlock):
            parts.append(block.text)
    return "\n".join(parts)


async def run_server(agent_factory: AgentFactory) -> None:
    """Start the ACP server over stdin/stdout.

    This is the main entry point for IDE integration.
    The IDE starts this process and communicates via ACP JSON-RPC.
    """
    server = MyrmAcpServer(agent_factory)
    await run_agent(server)  # type: ignore[arg-type]
