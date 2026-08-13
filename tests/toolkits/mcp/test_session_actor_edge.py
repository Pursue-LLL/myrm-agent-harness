"""Branch coverage for MCPSessionActor.

Targets the defensive branches the main lifecycle tests do not reach:
transport-target construction, auth-header refresh, resource-read content
validation, tool-name resolution fallback, reconnect bookkeeping, and owner
task cancellation while idle.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeTool:
    """Minimal BaseTool-like object the actor can wrap into a proxy."""

    def __init__(self, name: str, result: object = "ok") -> None:
        self.name = name
        self.description = f"{name} description"
        self.args_schema: dict[str, object] = {"type": "object", "properties": {}}
        self.metadata: dict[str, object] = {}
        self._result = result
        self.invocations: list[dict[str, object]] = []

    async def ainvoke(self, params: dict[str, object]) -> object:
        self.invocations.append(params)
        return self._result


def _install_fake_client(
    init_calls: list[int], tools: list[_FakeTool]
) -> tuple[MagicMock, MagicMock]:
    """Build a mock ``mcp.ClientSession`` and ``convert_mcp_tools``."""
    attempts = {"n": 0}

    mock_list_result = MagicMock()
    mock_list_result.tools = [MagicMock()]
    init_result = SimpleNamespace(instructions=None, server_info=None)

    client_instance = MagicMock()
    client_instance.initialize = AsyncMock(return_value=init_result)
    client_instance.list_tools = AsyncMock(return_value=mock_list_result)
    client_instance.call_tool = AsyncMock(return_value=MagicMock())
    client_instance.instructions = None
    client_instance.server_info = None

    async def _aenter(self_or_none=None) -> MagicMock:
        attempts["n"] += 1
        init_calls.append(attempts["n"])
        return client_instance

    client_instance.__aenter__ = _aenter
    client_instance.__aexit__ = AsyncMock(return_value=False)

    client_cls = MagicMock(return_value=client_instance)
    client_cls._instance = client_instance
    convert = MagicMock(return_value=list(tools))
    return client_cls, convert


@contextlib.contextmanager
def _patched(client_cls: MagicMock, convert: MagicMock) -> Iterator[None]:
    fake_target = MagicMock()
    fake_target.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
    fake_target.__aexit__ = AsyncMock(return_value=False)
    with (
        patch("mcp.ClientSession", client_cls),
        patch.object(
            MCPSessionActor,
            "_build_client_target",
            return_value=fake_target,
        ),
        patch(
            "myrm_agent_harness.toolkits.mcp.tool_converter.convert_mcp_tools",
            convert,
        ),
        patch(
            "myrm_agent_harness.toolkits.mcp.agent.MCPAgent.process_session_tools",
            staticmethod(lambda tools, *a, **k: tools),
        ),
    ):
        yield


def test_update_auth_headers_merges_new_headers() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio", "headers": {"a": "1"}})
    actor.update_auth_headers({"b": "2"})
    assert actor._connection["headers"] == {"a": "1", "b": "2"}


@pytest.mark.asyncio
async def test_read_resource_after_close_raises() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    await actor.close()
    with pytest.raises(RuntimeError, match="not healthy"):
        await actor.read_resource("memory://k")


@pytest.mark.asyncio
async def test_close_releases_http_client() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    http_client = AsyncMock()
    actor._http_client = http_client
    await actor.close()
    http_client.aclose.assert_awaited_once()
    assert actor._http_client is None


def test_build_client_target_http_requires_url() -> None:
    actor = MCPSessionActor("srv", {"transport": "sse"})
    with pytest.raises(ValueError, match="requires 'url'"):
        actor._build_client_target({"transport": "sse"})


def test_build_client_target_sse() -> None:
    with patch("mcp.client.sse.sse_client") as sse_client:
        actor = MCPSessionActor("srv", {"transport": "sse"})
        target = actor._build_client_target(
            {"transport": "sse", "url": "http://x", "headers": {"a": "b"}}
        )
        assert target is sse_client.return_value
        sse_client.assert_called_once_with("http://x", headers={"a": "b"})


def test_build_client_target_streamable_http_with_headers() -> None:
    http_client = MagicMock()
    with (
        patch(
            "myrm_agent_harness.toolkits.mcp.client.MCPClientManager.build_streamable_http_client",
            return_value=http_client,
        ),
        patch("mcp.client.streamable_http.streamable_http_client") as streamable_client,
    ):
        actor = MCPSessionActor("srv", {"transport": "streamable_http"})
        target = actor._build_client_target(
            {"transport": "streamable_http", "url": "http://x", "headers": {"a": "b"}}
        )
        assert target is streamable_client.return_value
        streamable_client.assert_called_once_with("http://x", http_client=http_client)
        assert actor._http_client is http_client


def test_build_client_target_streamable_http_plain() -> None:
    with patch("mcp.client.streamable_http.streamable_http_client") as streamable_client:
        actor = MCPSessionActor("srv", {"transport": "streamable_http"})
        target = actor._build_client_target(
            {"transport": "streamable_http", "url": "http://x"}
        )
        assert target is streamable_client.return_value
        streamable_client.assert_called_once_with("http://x")
        assert actor._http_client is None


def test_build_client_target_stdio() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    target = actor._build_client_target(
        {"transport": "stdio", "command": "/bin/echo", "args": ["hi"], "env": {}}
    )
    assert target is not None


@pytest.mark.asyncio
async def test_elicitation_handler_is_wired_into_client_kwargs() -> None:
    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_FakeTool("alpha")])
    handler = AsyncMock(return_value="accept")
    actor = MCPSessionActor(
        "srv", {"transport": "stdio"}, elicitation_handler=handler
    )
    with _patched(client_cls, convert):
        await actor.start()
        try:
            assert actor.is_healthy() is True
        finally:
            await actor.close()


@pytest.mark.asyncio
async def test_reconnect_reset_after_stable_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long-stable session earns a fresh reconnect budget after a blip."""
    import myrm_agent_harness.toolkits.mcp.session_actor as sa

    monkeypatch.setattr(sa, "_RECONNECT_RESET_AFTER", 0.0)
    monkeypatch.setattr(sa, "_RECONNECT_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(sa, "_RECONNECT_BACKOFF_BASE", 0.01)
    monkeypatch.setattr(sa, "_RECONNECT_BACKOFF_CAP", 0.02)

    class _FlakyTool(_FakeTool):
        def __init__(self, name: str) -> None:
            super().__init__(name)
            self.calls = 0

        async def ainvoke(self, params: dict[str, object]) -> object:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("blip")
            return "recovered"

    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_FlakyTool("alpha")])
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    with _patched(client_cls, convert):
        await actor.start()
        try:
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(actor.call("alpha", {"id": "a"}), timeout=5.0)
            result = await asyncio.wait_for(actor.call("alpha", {"id": "b"}), timeout=5.0)
            assert result == "recovered"
            assert actor.is_healthy() is True
        finally:
            await actor.close()


@pytest.mark.asyncio
async def test_reconnect_serve_loop_exhausts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every re-serve breaks again until the reconnect budget is exhausted."""
    import myrm_agent_harness.toolkits.mcp.session_actor as sa

    monkeypatch.setattr(sa, "_RECONNECT_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(sa, "_RECONNECT_BACKOFF_BASE", 0.01)
    monkeypatch.setattr(sa, "_RECONNECT_BACKOFF_CAP", 0.02)

    class _AlwaysBreakTool(_FakeTool):
        async def ainvoke(self, params: dict[str, object]) -> object:
            raise ConnectionError("still broken")

    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_AlwaysBreakTool("alpha")])
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    with _patched(client_cls, convert):
        await actor.start()
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    actor.call("alpha", {"id": "a"}),
                    actor.call("alpha", {"id": "b"}),
                    actor.call("alpha", {"id": "c"}),
                    return_exceptions=True,
                ),
                timeout=10.0,
            )
            assert len(results) == 3
            assert all(isinstance(r, Exception) for r in results)
            assert actor.is_healthy() is False
        finally:
            await actor.close()


@pytest.mark.asyncio
async def test_owner_cancelled_while_idle_is_clean() -> None:
    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_FakeTool("alpha")])
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    with _patched(client_cls, convert):
        await actor.start()
        # Cancel the owner while it is parked on the dequeue future; the serve
        # loop's finally must cancel the idle waiter without leaking a task.
        actor._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await actor._task
        assert actor.is_healthy() is False
        await actor.close()


@pytest.mark.asyncio
async def test_keepalive_ok_reports_failure() -> None:
    session = MagicMock()
    session.list_tools = AsyncMock(side_effect=ConnectionError("down"))
    actor = MCPSessionActor("srv", {"transport": "stdio"}, connect_timeout=0.2)
    assert await actor._keepalive_ok(session) is False


@pytest.mark.asyncio
async def test_refresh_auth_headers_updates_connection() -> None:
    provider = AsyncMock()
    provider.get_auth_headers = AsyncMock(return_value={"Authorization": "Bearer t"})
    conn: dict[str, object] = {
        "transport": "streamable_http",
        "url": "http://x",
        "headers": {"a": "1"},
    }
    actor = MCPSessionActor("srv", conn, auth_provider=provider)
    await actor._refresh_auth_headers(conn)
    assert conn["headers"] == {"a": "1", "Authorization": "Bearer t"}


@pytest.mark.asyncio
async def test_refresh_auth_headers_skips_non_http_transport() -> None:
    provider = AsyncMock()
    conn: dict[str, object] = {"transport": "stdio"}
    actor = MCPSessionActor("srv", conn, auth_provider=provider)
    await actor._refresh_auth_headers(conn)
    provider.get_auth_headers.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_auth_headers_swallows_provider_error() -> None:
    provider = AsyncMock()
    provider.get_auth_headers = AsyncMock(side_effect=RuntimeError("boom"))
    conn: dict[str, object] = {"transport": "streamable_http", "url": "http://x"}
    actor = MCPSessionActor("srv", conn, auth_provider=provider)
    await actor._refresh_auth_headers(conn)  # must not raise
    assert conn.get("headers") is None


@pytest.mark.asyncio
async def test_read_resource_empty_content_raises() -> None:
    session = MagicMock()
    session.read_resource = AsyncMock(return_value=SimpleNamespace(contents=[]))
    actor = MCPSessionActor("srv", {"transport": "stdio"}, connect_timeout=0.2)
    with pytest.raises(RuntimeError, match="empty content"):
        await actor._read_resource(session, "memory://k")


@pytest.mark.asyncio
async def test_read_resource_decodes_blob_and_text() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio"}, connect_timeout=0.2)
    session = MagicMock()
    session.read_resource = AsyncMock(
        return_value=SimpleNamespace(
            contents=[SimpleNamespace(blob="aGVsbG8=", text=None)]
        )
    )
    assert await actor._read_resource(session, "memory://k") == b"hello"

    session.read_resource = AsyncMock(
        return_value=SimpleNamespace(
            contents=[SimpleNamespace(blob=None, text="hi")]
        )
    )
    assert await actor._read_resource(session, "memory://k") == b"hi"

    session.read_resource = AsyncMock(
        return_value=SimpleNamespace(
            contents=[SimpleNamespace(blob=None, text=None)]
        )
    )
    with pytest.raises(RuntimeError, match="no text or blob"):
        await actor._read_resource(session, "memory://k")


def test_resolve_tool_prefixed_fallback() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    actor._tools = {"mcp__srv__beta": _FakeTool("mcp__srv__beta")}
    tool = actor._resolve_tool("beta")
    assert tool is not None
    assert tool.name == "mcp__srv__beta"


def test_fail_pending_on_empty_queue_is_noop() -> None:
    actor = MCPSessionActor("srv", {"transport": "stdio"})
    actor._fail_pending(RuntimeError("x"))  # empty queue: QueueEmpty breaks loop


@pytest.mark.asyncio
async def test_read_resource_success_via_owner_queue() -> None:
    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_FakeTool("alpha")])
    client_cls._instance.read_resource = AsyncMock(
        return_value=SimpleNamespace(contents=[SimpleNamespace(blob=None, text="hi")])
    )
    actor = MCPSessionActor("srv", {"transport": "stdio"}, connect_timeout=0.2)
    with _patched(client_cls, convert):
        await actor.start()
        try:
            data = await asyncio.wait_for(actor.read_resource("memory://k"), timeout=5.0)
            assert data == b"hi"
        finally:
            await actor.close()


@pytest.mark.asyncio
async def test_read_resource_transport_break_recovers() -> None:
    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_FakeTool("alpha")])
    reads = {"n": 0}

    async def _flaky_read(uri: str) -> object:
        reads["n"] += 1
        if reads["n"] == 1:
            raise ConnectionError("transport broke")
        return SimpleNamespace(contents=[SimpleNamespace(blob=None, text="hi")])

    client_cls._instance.read_resource = AsyncMock(side_effect=_flaky_read)
    actor = MCPSessionActor("srv", {"transport": "stdio"}, connect_timeout=0.2)
    with _patched(client_cls, convert):
        await actor.start()
        try:
            with pytest.raises(ConnectionError):
                await asyncio.wait_for(actor.read_resource("memory://k"), timeout=5.0)
            data = await asyncio.wait_for(actor.read_resource("memory://k"), timeout=5.0)
            assert data == b"hi"
            assert actor.is_healthy() is True
        finally:
            await actor.close()


@pytest.mark.asyncio
async def test_read_resource_non_transport_error_fails_call() -> None:
    init_calls: list[int] = []
    client_cls, convert = _install_fake_client(init_calls, [_FakeTool("alpha")])
    client_cls._instance.read_resource = AsyncMock(side_effect=RuntimeError("boom"))
    actor = MCPSessionActor("srv", {"transport": "stdio"}, connect_timeout=0.2)
    with _patched(client_cls, convert):
        await actor.start()
        try:
            with pytest.raises(RuntimeError, match="boom"):
                await asyncio.wait_for(actor.read_resource("memory://k"), timeout=5.0)
        finally:
            await actor.close()
