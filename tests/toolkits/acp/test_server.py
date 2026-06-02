"""Tests for MyrmAcpServer — protocol layer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from acp.schema import TextContentBlock

from myrm_agent_harness.toolkits.acp.server.server import MyrmAcpServer, _extract_text


class _StubFactory:
    async def create_agent(self, session_id: str, cwd: str) -> object:
        return MagicMock()


@pytest.fixture
def server() -> MyrmAcpServer:
    return MyrmAcpServer(_StubFactory())  # type: ignore[arg-type]


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_returns_response(self, server: MyrmAcpServer) -> None:
        result = await server.initialize(protocol_version=1)
        assert result.protocol_version >= 1
        assert result.agent_info.name == "myrm-agent"


class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_new_session(self, server: MyrmAcpServer) -> None:
        result = await server.new_session(cwd="/tmp")
        assert result.session_id

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, server: MyrmAcpServer) -> None:
        result = await server.list_sessions()
        assert result.sessions == []

    @pytest.mark.asyncio
    async def test_list_sessions_after_create(self, server: MyrmAcpServer) -> None:
        await server.new_session(cwd="/tmp")
        result = await server.list_sessions()
        assert len(result.sessions) == 1

    @pytest.mark.asyncio
    async def test_close_session(self, server: MyrmAcpServer) -> None:
        resp = await server.new_session(cwd="/tmp")
        result = await server.close_session(session_id=resp.session_id)
        assert result is not None
        sessions = await server.list_sessions()
        assert len(sessions.sessions) == 0

    @pytest.mark.asyncio
    async def test_load_existing_session(self, server: MyrmAcpServer) -> None:
        resp = await server.new_session(cwd="/tmp")
        result = await server.load_session(cwd="/tmp", session_id=resp.session_id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_load_nonexistent_session(self, server: MyrmAcpServer) -> None:
        result = await server.load_session(cwd="/tmp", session_id="nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_fork_session(self, server: MyrmAcpServer) -> None:
        resp = await server.new_session(cwd="/tmp")
        fork_resp = await server.fork_session(cwd="/tmp2", session_id=resp.session_id)
        assert fork_resp.session_id != resp.session_id

    @pytest.mark.asyncio
    async def test_resume_existing_session(self, server: MyrmAcpServer) -> None:
        resp = await server.new_session(cwd="/tmp")
        result = await server.resume_session(cwd="/tmp", session_id=resp.session_id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_resume_nonexistent_creates_new(self, server: MyrmAcpServer) -> None:
        sessions_before = (await server.list_sessions()).sessions
        result = await server.resume_session(cwd="/tmp", session_id="gone")
        assert result is not None
        sessions_after = (await server.list_sessions()).sessions
        assert len(sessions_after) == len(sessions_before) + 1


class TestPrompt:
    @pytest.mark.asyncio
    async def test_empty_prompt_returns_end_turn(self, server: MyrmAcpServer) -> None:
        await server.new_session(cwd="/tmp")
        result = await server.prompt(prompt=[], session_id="s1")
        assert result.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_prompt_without_connection_returns_end_turn(self, server: MyrmAcpServer) -> None:
        resp = await server.new_session(cwd="/tmp")
        blocks = [TextContentBlock(type="text", text="hello")]
        result = await server.prompt(prompt=blocks, session_id=resp.session_id)
        assert result.stop_reason == "end_turn"


class TestOptionalMethods:
    @pytest.mark.asyncio
    async def test_set_session_mode_returns_none(self, server: MyrmAcpServer) -> None:
        assert await server.set_session_mode(mode_id="agent", session_id="s1") is None

    @pytest.mark.asyncio
    async def test_set_session_model_returns_none(self, server: MyrmAcpServer) -> None:
        assert await server.set_session_model(model_id="gpt-4", session_id="s1") is None

    @pytest.mark.asyncio
    async def test_set_config_option_returns_none(self, server: MyrmAcpServer) -> None:
        assert await server.set_config_option(config_id="c1", session_id="s1", value=True) is None

    @pytest.mark.asyncio
    async def test_authenticate_returns_none(self, server: MyrmAcpServer) -> None:
        assert await server.authenticate(method_id="oauth") is None

    @pytest.mark.asyncio
    async def test_ext_method_returns_empty(self, server: MyrmAcpServer) -> None:
        assert await server.ext_method("custom", {}) == {}

    @pytest.mark.asyncio
    async def test_ext_notification_is_noop(self, server: MyrmAcpServer) -> None:
        await server.ext_notification("custom", {})


class TestExtractText:
    def test_single_text_block(self) -> None:
        blocks = [TextContentBlock(type="text", text="hello")]
        assert _extract_text(blocks) == "hello"  # type: ignore[arg-type]

    def test_multiple_text_blocks(self) -> None:
        blocks = [
            TextContentBlock(type="text", text="line1"),
            TextContentBlock(type="text", text="line2"),
        ]
        assert _extract_text(blocks) == "line1\nline2"  # type: ignore[arg-type]

    def test_empty_blocks(self) -> None:
        assert _extract_text([]) == ""  # type: ignore[arg-type]
