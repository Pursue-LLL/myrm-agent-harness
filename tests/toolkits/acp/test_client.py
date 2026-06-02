"""Tests for ACP runtime system — types, base, pool, permission, event_bus."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.event_bus import EventBus
from myrm_agent_harness.toolkits.acp.permission import DefaultPermissionManager
from myrm_agent_harness.toolkits.acp.runtime._base import BaseRuntime, build_safe_env, truncate_response
from myrm_agent_harness.toolkits.acp.runtime.acp_callback import AcpCallbackHandler
from myrm_agent_harness.toolkits.acp.runtime.pool import RuntimePool
from myrm_agent_harness.toolkits.acp.types import (
    AcpErrorCode,
    BackendCapabilities,
    BackendInfo,
    PermissionDecision,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeEventType,
    create_event,
    create_permission_request,
)


# ---------------------------------------------------------------------------
# RuntimeConfig
# ---------------------------------------------------------------------------
class TestRuntimeConfig:
    def test_defaults(self) -> None:
        cfg = RuntimeConfig(backend_type="acp", command="claude")
        assert cfg.command == "claude"
        assert cfg.args == []
        assert cfg.env is None
        assert cfg.cwd is None
        assert cfg.timeout_seconds == 300
        assert cfg.permission_mode == "allow_all"
        assert cfg.allowed_tools == []
        assert cfg.max_response_chars == 50_000

    def test_custom_values(self) -> None:
        cfg = RuntimeConfig(
            backend_type="cli",
            command="codex",
            args=["--acp"],
            env={"MY_VAR": "1"},
            cwd="/workspace",
            timeout_seconds=120,
            permission_mode="safe",
            allowed_tools=["Read", "Bash(npm run *)"],
        )
        assert cfg.command == "codex"
        assert cfg.backend_type == "cli"
        assert cfg.timeout_seconds == 120
        assert cfg.permission_mode == "safe"

    def test_max_turns_default(self) -> None:
        cfg = RuntimeConfig(backend_type="acp", command="test")
        assert cfg.max_turns == 25

    def test_description_default(self) -> None:
        cfg = RuntimeConfig(backend_type="acp", command="test")
        assert cfg.description == ""

    def test_custom_max_turns_and_description(self) -> None:
        cfg = RuntimeConfig(
            backend_type="cli",
            command="claude",
            max_turns=50,
            description="A powerful coding agent",
        )
        assert cfg.max_turns == 50
        assert cfg.description == "A powerful coding agent"

    def test_max_turns_zero_disables(self) -> None:
        cfg = RuntimeConfig(backend_type="cli", command="claude", max_turns=0)
        assert cfg.max_turns == 0

    def test_frozen(self) -> None:
        cfg = RuntimeConfig(backend_type="acp", command="test")
        with pytest.raises(AttributeError):
            cfg.command = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_safe_env
# ---------------------------------------------------------------------------
class TestBuildSafeEnv:
    def test_strips_sensitive_keys(self) -> None:
        base = {
            "HOME": "/home/user",
            "OPENAI_API_KEY": "sk-secret",
            "ANTHROPIC_API_KEY": "ant-secret",
            "PATH": "/usr/bin",
        }
        cfg = RuntimeConfig(backend_type="acp", command="test")
        env = build_safe_env(cfg, base)
        assert "OPENAI_API_KEY" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert env["HOME"] == "/home/user"
        assert env["PATH"] == "/usr/bin"

    def test_strips_explicit_keys(self) -> None:
        base = {"MY_SECRET": "val", "KEEP_ME": "yes"}
        cfg = RuntimeConfig(backend_type="acp", command="test", strip_env_keys=["MY_SECRET"])
        env = build_safe_env(cfg, base)
        assert "MY_SECRET" not in env
        assert env["KEEP_ME"] == "yes"

    def test_applies_config_env_after_strip(self) -> None:
        # api_key mode lets the host inject the provider key this backend bills against;
        # it is re-applied after the baseline strip removes the inherited one.
        base = {"OPENAI_API_KEY": "old-key"}
        cfg = RuntimeConfig(
            backend_type="acp", command="test", auth_mode="api_key", env={"OPENAI_API_KEY": "new-key"}
        )
        env = build_safe_env(cfg, base)
        assert env["OPENAI_API_KEY"] == "new-key"

    def test_subscription_drops_injected_secret(self) -> None:
        # subscription mode (default) forces the CLI onto its login session by dropping
        # any injected provider secret, so a stale key can't silently bill the user.
        base = {"OPENAI_API_KEY": "old-key"}
        cfg = RuntimeConfig(backend_type="acp", command="test", env={"OPENAI_API_KEY": "new-key"})
        env = build_safe_env(cfg, base)
        assert "OPENAI_API_KEY" not in env


# ---------------------------------------------------------------------------
# truncate_response
# ---------------------------------------------------------------------------
class TestTruncateResponse:
    def test_no_truncation(self) -> None:
        assert truncate_response("short", 100) == "short"

    def test_truncation(self) -> None:
        result = truncate_response("a" * 200, 100)
        assert len(result) > 100
        assert "[truncated" in result


# ---------------------------------------------------------------------------
# RuntimeEvent & helpers
# ---------------------------------------------------------------------------
class TestRuntimeEvent:
    def test_create_event(self) -> None:
        event = create_event(RuntimeEventType.TEXT_DELTA, "sess-1", content="hello")
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "hello"
        assert event.session_id == "sess-1"
        assert event.timestamp > 0

    @pytest.mark.asyncio
    async def test_create_permission_request(self) -> None:
        event, _future = create_permission_request("sess-1", "Write", {"path": "/tmp"})
        assert event.type == RuntimeEventType.PERMISSION_REQUEST
        assert event.data["tool_name"] == "Write"
        assert "response_future" in event.data

    def test_event_types_count(self) -> None:
        assert len(RuntimeEventType) == 9

    def test_error_codes_count(self) -> None:
        assert len(AcpErrorCode) == 9
        assert AcpErrorCode.PERMISSION_DENIED == "permission_denied"


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------
class TestEventBus:
    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self) -> None:
        bus = EventBus()
        received: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: received.append(e))
        event = create_event(RuntimeEventType.TEXT_DELTA, "s1", content="hi")
        await bus.emit(event)
        assert len(received) == 1
        assert received[0].data["content"] == "hi"

    @pytest.mark.asyncio
    async def test_event_type_filter(self) -> None:
        bus = EventBus()
        errors: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: errors.append(e), event_type=RuntimeEventType.ERROR)
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="hi"))
        await bus.emit(create_event(RuntimeEventType.ERROR, "s1", error="fail"))
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_session_filter(self) -> None:
        bus = EventBus()
        s1_events: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: s1_events.append(e), session_id="s1")
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="a"))
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s2", content="b"))
        assert len(s1_events) == 1

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[RuntimeEvent] = []
        sub_id = bus.subscribe(callback=lambda e: received.append(e))
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="a"))
        bus.unsubscribe(sub_id)
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="b"))
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_async_callback(self) -> None:
        bus = EventBus()
        received: list[str] = []

        async def handler(e: RuntimeEvent) -> None:
            received.append(str(e.data.get("content", "")))

        bus.subscribe(callback=handler)
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="async"))
        assert received == ["async"]


# ---------------------------------------------------------------------------
# DefaultPermissionManager
# ---------------------------------------------------------------------------
class TestDefaultPermissionManager:
    @pytest.mark.asyncio
    async def test_allow_all_mode(self) -> None:
        pm = DefaultPermissionManager(mode="allow_all")
        assert await pm.check("Write", {}, "s1") == PermissionDecision.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_safe_mode_allows_read(self) -> None:
        pm = DefaultPermissionManager(mode="safe")
        assert await pm.check("Read", {}, "s1") == PermissionDecision.ALLOW_ONCE
        assert await pm.check("read_file", {}, "s1") == PermissionDecision.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_safe_mode_denies_write(self) -> None:
        pm = DefaultPermissionManager(mode="safe")
        assert await pm.check("Write", {}, "s1") == PermissionDecision.DENY_ONCE

    @pytest.mark.asyncio
    async def test_bypass_mode(self) -> None:
        pm = DefaultPermissionManager(mode="bypass")
        assert await pm.check("anything", {}, "s1") == PermissionDecision.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_allowlist_exact_match(self) -> None:
        pm = DefaultPermissionManager(mode="safe", allowed_tools=["Write"])
        assert await pm.check("Write", {}, "s1") == PermissionDecision.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_allowlist_wildcard(self) -> None:
        pm = DefaultPermissionManager(mode="safe", allowed_tools=["Bash(npm run *)"])
        assert await pm.check("Bash", {"command": "npm run test"}, "s1") == PermissionDecision.ALLOW_ONCE
        assert await pm.check("Bash", {"command": "rm -rf /"}, "s1") == PermissionDecision.DENY_ONCE

    @pytest.mark.asyncio
    async def test_session_approval_cache(self) -> None:
        pm = DefaultPermissionManager(mode="ask")
        pm.record_approval("Write", "s1")
        assert await pm.check("Write", {}, "s1") == PermissionDecision.ALLOW_ONCE
        assert await pm.check("Write", {}, "s2") == PermissionDecision.DENY_ONCE


class TestAcpCallbackHandlerPermission:
    @pytest.mark.asyncio
    async def test_request_permission_ask_mode_waits_for_future(self) -> None:
        bus = EventBus()
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="ask"),
            "test-session",
            event_bus=bus,
            permission_request_timeout=0.5,
        )
        received: list[dict[str, object]] = []

        async def on_event(event: RuntimeEvent) -> None:
            received.append(event.data)
            future = event.data.get("response_future")
            if isinstance(future, asyncio.Future):
                future.set_result(PermissionDecision.ALLOW_ONCE)

        bus.subscribe(callback=on_event)
        options = [
            {"kind": "allow_once", "optionId": "allow_once"},
            {"kind": "reject_once", "optionId": "reject_once"},
        ]

        result = await handler.request_permission(options, "test-session", {"name": "Write", "path": "/tmp"})

        assert result == {"outcome": {"outcome": "selected", "optionId": "allow_once"}}
        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_request_permission_ask_mode_times_out_to_deny(self) -> None:
        bus = EventBus()
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="ask"),
            "test-session",
            event_bus=bus,
            permission_request_timeout=0.001,
        )

        options = [{"kind": "allow_once", "optionId": "allow_once"}, {"kind": "reject_once", "optionId": "reject_once"}]
        result = await handler.request_permission(options, "test-session", {"name": "Write", "path": "/tmp"})

        assert result["outcome"]["outcome"] == "selected"
        assert result["outcome"]["optionId"] == "reject_once"

    @pytest.mark.asyncio
    async def test_request_permission_ask_mode_without_bus_falls_back_to_deny(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="ask"),
            "test-session",
        )
        options = [{"kind": "allow_once", "optionId": "allow_once"}]
        result = await handler.request_permission(options, "test-session", {"name": "Write", "path": "/tmp"})

        assert result["outcome"]["outcome"] == "cancelled"


# ---------------------------------------------------------------------------
# RuntimePool
# ---------------------------------------------------------------------------
class TestRuntimePool:
    class _DummyRuntimeBackend:
        def __init__(self, name: str = "test-backend") -> None:
            self._name = name
            self.closed = False

        @property
        def name(self) -> str:
            return self._name

        @property
        def capabilities(self):
            return BackendCapabilities()

        @property
        def is_alive(self) -> bool:
            return not self.closed

        async def run_turn(self, prompt: str, session_id: str, *, mcp_servers=None):
            yield create_event(RuntimeEventType.STATUS_UPDATE, session_id, status="starting")
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content=prompt)
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        async def cancel(self, session_id: str) -> None:
            return None

        async def resume(self, session_id: str) -> bool:
            return False

        async def get_info(self):
            return BackendInfo(name=self._name)

        async def close(self) -> None:
            self.closed = True

    def test_available_backends(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        pool.register("codex", RuntimeConfig(backend_type="cli", command="codex"))
        assert sorted(pool.available_backends) == ["claude", "codex"]

    def test_get_known_backend(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        backend = pool.get("claude")
        assert backend.name == "claude"

    def test_get_unknown_backend_raises(self) -> None:
        pool = RuntimePool()
        with pytest.raises(KeyError, match="Unknown backend"):
            pool.get("nonexistent")

    def test_get_returns_same_instance(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        b1 = pool.get("claude")
        b2 = pool.get("claude")
        assert b1 is b2

    @pytest.mark.asyncio
    async def test_prompt_persistent_mode_keeps_backend(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        backend = self._DummyRuntimeBackend("claude")

        with patch.object(pool, "get", return_value=backend):
            result = await pool.prompt("claude", "task", mode="persistent")

        assert result == "task"
        assert not backend.closed

    @pytest.mark.asyncio
    async def test_prompt_oneshot_closes_backend(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        backend = self._DummyRuntimeBackend("claude")

        with patch.object(pool, "get", return_value=backend):
            result = await pool.prompt("claude", "task", mode="oneshot")

        assert result == "task"
        assert backend.closed

    @pytest.mark.asyncio
    async def test_prompt_invalid_mode_raises(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))

        with pytest.raises(ValueError, match="Invalid mode"):
            await pool.prompt("claude", "task", mode="invalid")

    @pytest.mark.asyncio
    async def test_run_turn_oneshot_closes_backend(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        backend = self._DummyRuntimeBackend("claude")

        with patch.object(pool, "get", return_value=backend):
            events = [e async for e in pool.run_turn("claude", "task", session_id="s-1", mode="oneshot")]

        assert len(events) == 3
        assert backend.closed

    @pytest.mark.asyncio
    async def test_run_turn_invalid_mode_raises(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        with pytest.raises(ValueError, match="Invalid mode"):
            [e async for e in pool.run_turn("claude", "task", "s-1", mode="bad")]

    @pytest.mark.asyncio
    async def test_event_bus_emits_events(self) -> None:
        bus = EventBus()
        recorded = []
        bus.subscribe(callback=lambda e: recorded.append(e))

        pool = RuntimePool(event_bus=bus)
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        backend = self._DummyRuntimeBackend("claude")

        with patch.object(pool, "get", return_value=backend):
            events = [e async for e in pool.run_turn("claude", "task", "s-1")]

        assert recorded == events


# ---------------------------------------------------------------------------
# BaseRuntime (template methods)
# ---------------------------------------------------------------------------
class TestBaseRuntime:
    @pytest.mark.asyncio
    async def test_get_info(self) -> None:
        rt = BaseRuntime("test-rt", RuntimeConfig(backend_type="acp", command="test"), "acp")
        info = await rt.get_info()
        assert info.name == "test-rt"
        assert info.backend_type == "acp"
        assert info.status == "stopped"

    @pytest.mark.asyncio
    async def test_close_sets_alive_false(self) -> None:
        rt = BaseRuntime("test-rt", RuntimeConfig(backend_type="acp", command="test"), "acp")
        rt._alive = True
        await rt.close()
        assert rt.is_alive is False

    @pytest.mark.asyncio
    async def test_cancel_suppresses_errors(self) -> None:
        rt = BaseRuntime("test-rt", RuntimeConfig(backend_type="acp", command="test"), "acp")
        await rt.cancel("s1")

    @pytest.mark.asyncio
    async def test_resume_returns_false(self) -> None:
        rt = BaseRuntime("test-rt", RuntimeConfig(backend_type="acp", command="test"), "acp")
        assert await rt.resume("s1") is False

    def test_capabilities_default(self) -> None:
        rt = BaseRuntime("test-rt", RuntimeConfig(backend_type="acp", command="test"), "acp")
        caps = rt.capabilities
        assert caps.supports_resume is False
        assert caps.supports_streaming is True


# ---------------------------------------------------------------------------
# AcpCallbackHandler (session_update, read/write)
# ---------------------------------------------------------------------------
class TestAcpCallbackHandlerSessionUpdate:
    @pytest.mark.asyncio
    async def test_agent_message_chunk_text(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy"),
            "s1",
        )
        update = MagicMock()
        update.session_update = "agent_message_chunk"
        update.sessionUpdate = None
        update.content = MagicMock()
        update.content.type = "text"
        update.content.text = "hello world"
        await handler.session_update("s1", update)
        assert "hello world" in handler.response_text

    @pytest.mark.asyncio
    async def test_tool_call_update(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy"),
            "s1",
        )
        update = MagicMock()
        update.session_update = "tool_call"
        update.sessionUpdate = None
        update.title = "bash"
        update.status = "running"
        update.content = None
        await handler.session_update("s1", update)
        assert "bash" in handler.response_text

    @pytest.mark.asyncio
    async def test_tool_call_update_completed(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy"),
            "s1",
        )
        update = MagicMock()
        update.session_update = "tool_call_update"
        update.sessionUpdate = None
        update.status = "completed"
        update.tool_call_id = "tc1"
        update.toolCallId = None
        update.content = None
        await handler.session_update("s1", update)
        assert "tc1" in handler.response_text

    @pytest.mark.asyncio
    async def test_agent_thought_chunk(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy"),
            "s1",
        )
        update = MagicMock()
        update.session_update = "agent_thought_chunk"
        update.sessionUpdate = None
        update.content = MagicMock()
        update.content.type = "text"
        update.content.text = "thinking..."
        await handler.session_update("s1", update)
        assert "thinking..." in handler.response_text

    @pytest.mark.asyncio
    async def test_reset_clears_text(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy"),
            "s1",
        )
        handler._text_parts.append("old text")
        handler.reset()
        assert handler.response_text == ""


class TestAcpCallbackHandlerFileOps:
    @pytest.mark.asyncio
    async def test_read_text_file_within_cwd(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("file content", encoding="utf-8")
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path)),
            "s1",
        )
        result = await handler.read_text_file(str(test_file), "s1")
        assert result["content"] == "file content"

    @pytest.mark.asyncio
    async def test_read_text_file_with_line_range(self, tmp_path: Path) -> None:
        test_file = tmp_path / "test.txt"
        test_file.write_text("line1\nline2\nline3\n", encoding="utf-8")
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path)),
            "s1",
        )
        result = await handler.read_text_file(str(test_file), "s1", limit=1, line=2)
        assert "line2" in result["content"]

    @pytest.mark.asyncio
    async def test_read_text_file_outside_cwd(self, tmp_path: Path) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path / "sub")),
            "s1",
        )
        result = await handler.read_text_file("/etc/passwd", "s1")
        assert "[error]" in result["content"]

    @pytest.mark.asyncio
    async def test_read_text_file_nonexistent(self, tmp_path: Path) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path)),
            "s1",
        )
        result = await handler.read_text_file(str(tmp_path / "nope.txt"), "s1")
        assert "[error]" in result["content"]

    @pytest.mark.asyncio
    async def test_write_text_file_allow_all(self, tmp_path: Path) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path), permission_mode="allow_all"),
            "s1",
        )
        target = tmp_path / "output.txt"
        result = await handler.write_text_file("content", str(target), "s1")
        assert result == {"success": True}
        assert target.read_text() == "content"

    @pytest.mark.asyncio
    async def test_write_text_file_safe_mode_denied(self, tmp_path: Path) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path), permission_mode="safe"),
            "s1",
        )
        result = await handler.write_text_file("content", str(tmp_path / "out.txt"), "s1")
        assert result is None

    @pytest.mark.asyncio
    async def test_write_text_file_outside_cwd(self, tmp_path: Path) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", cwd=str(tmp_path), permission_mode="allow_all"),
            "s1",
        )
        result = await handler.write_text_file("content", "/tmp/evil.txt", "s1")
        assert result is None


class TestAcpCallbackHandlerPermissionModes:
    @pytest.mark.asyncio
    async def test_safe_mode_allows_read_ops(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="safe"),
            "s1",
        )
        options = [
            {"kind": "allow_once", "optionId": "allow_once"},
            {"kind": "reject_once", "optionId": "reject_once"},
        ]
        result = await handler.request_permission(options, "s1", {"name": "read_file"})
        assert result["outcome"]["optionId"] == "allow_once"

    @pytest.mark.asyncio
    async def test_safe_mode_rejects_write_ops(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="safe"),
            "s1",
        )
        options = [
            {"kind": "allow_once", "optionId": "allow_once"},
            {"kind": "reject_once", "optionId": "reject_once"},
        ]
        result = await handler.request_permission(options, "s1", {"name": "Write"})
        assert result["outcome"]["optionId"] == "reject_once"

    @pytest.mark.asyncio
    async def test_bypass_mode(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="bypass"),
            "s1",
        )
        options = [{"kind": "allow_always", "optionId": "allow_always"}]
        result = await handler.request_permission(options, "s1", {"name": "Write"})
        assert result["outcome"]["optionId"] == "allow_always"

    @pytest.mark.asyncio
    async def test_allow_all_mode(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="allow_all"),
            "s1",
        )
        options = [
            {"kind": "allow_once", "optionId": "allow_once"},
            {"kind": "allow_always", "optionId": "allow_always"},
        ]
        result = await handler.request_permission(options, "s1", {"name": "Write"})
        assert result["outcome"]["outcome"] == "selected"

    @pytest.mark.asyncio
    async def test_safe_mode_no_reject_option_cancels(self) -> None:
        handler = AcpCallbackHandler(
            RuntimeConfig(backend_type="acp", command="dummy", permission_mode="safe"),
            "s1",
        )
        options = [{"kind": "allow_once", "optionId": "allow_once"}]
        result = await handler.request_permission(options, "s1", {"name": "Write"})
        assert result["outcome"]["outcome"] == "cancelled"


# ---------------------------------------------------------------------------
# EventBus edge cases
# ---------------------------------------------------------------------------
class TestEventBusEdgeCases:
    @pytest.mark.asyncio
    async def test_callback_error_does_not_propagate(self) -> None:
        bus = EventBus()

        def bad_callback(e: RuntimeEvent) -> None:
            raise ValueError("callback error")

        bus.subscribe(callback=bad_callback)
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="test"))

    @pytest.mark.asyncio
    async def test_clear_removes_all_subscriptions(self) -> None:
        bus = EventBus()
        received: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: received.append(e))
        bus.clear()
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="test"))
        assert received == []

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_is_noop(self) -> None:
        bus = EventBus()
        bus.unsubscribe(999)

    @pytest.mark.asyncio
    async def test_combined_type_and_session_filter(self) -> None:
        bus = EventBus()
        matched: list[RuntimeEvent] = []
        bus.subscribe(
            callback=lambda e: matched.append(e),
            event_type=RuntimeEventType.ERROR,
            session_id="s1",
        )
        await bus.emit(create_event(RuntimeEventType.ERROR, "s1", error="match"))
        await bus.emit(create_event(RuntimeEventType.ERROR, "s2", error="wrong session"))
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="wrong type"))
        assert len(matched) == 1
        assert matched[0].data["error"] == "match"

    @pytest.mark.asyncio
    async def test_multiple_subscribers_all_receive(self) -> None:
        bus = EventBus()
        r1: list[RuntimeEvent] = []
        r2: list[RuntimeEvent] = []
        bus.subscribe(callback=lambda e: r1.append(e))
        bus.subscribe(callback=lambda e: r2.append(e))
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="broadcast"))
        assert len(r1) == 1
        assert len(r2) == 1

    @pytest.mark.asyncio
    async def test_async_callback_error_does_not_propagate(self) -> None:
        bus = EventBus()

        async def bad_async(e: RuntimeEvent) -> None:
            raise ValueError("async boom")

        bus.subscribe(callback=bad_async)
        await bus.emit(create_event(RuntimeEventType.TEXT_DELTA, "s1", content="test"))


# ---------------------------------------------------------------------------
# DefaultPermissionManager edge cases
# ---------------------------------------------------------------------------
class TestPermissionManagerEdgeCases:
    @pytest.mark.asyncio
    async def test_clear_session_cache(self) -> None:
        pm = DefaultPermissionManager(mode="ask")
        pm.record_approval("Write", "s1")
        pm.clear_session_cache("s1")
        assert await pm.check("Write", {}, "s1") == PermissionDecision.DENY_ONCE

    @pytest.mark.asyncio
    async def test_allowlist_empty_pattern(self) -> None:
        pm = DefaultPermissionManager(mode="safe", allowed_tools=["Bash()"])
        assert await pm.check("Bash", {"command": "anything"}, "s1") == PermissionDecision.ALLOW_ONCE

    @pytest.mark.asyncio
    async def test_allowlist_no_match(self) -> None:
        pm = DefaultPermissionManager(mode="safe", allowed_tools=["Read"])
        assert await pm.check("Write", {}, "s1") == PermissionDecision.DENY_ONCE

    def test_mode_property(self) -> None:
        pm = DefaultPermissionManager(mode="safe")
        assert pm.mode == "safe"


# ---------------------------------------------------------------------------
# RuntimePool close_all
# ---------------------------------------------------------------------------
class TestRuntimePoolCloseAll:
    @pytest.mark.asyncio
    async def test_close_all_handles_errors(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        backend = MagicMock()
        backend.close = AsyncMock(side_effect=RuntimeError("close failed"))
        pool._backends["claude"] = backend
        await pool.close_all()
        assert pool._backends == {}

    @pytest.mark.asyncio
    async def test_close_all_empty(self) -> None:
        pool = RuntimePool()
        await pool.close_all()


class TestRuntimePoolConcurrency:
    """Tests for RuntimePool semaphore-based concurrency control."""

    class _SlowBackend:
        def __init__(self, name: str, delay: float = 0.05) -> None:
            self._name = name
            self._delay = delay
            self.concurrent_count = 0
            self.max_concurrent = 0
            self.closed = False

        @property
        def name(self) -> str:
            return self._name

        @property
        def capabilities(self):
            return BackendCapabilities()

        @property
        def is_alive(self) -> bool:
            return True

        async def run_turn(self, prompt: str, session_id: str, *, mcp_servers=None):
            self.concurrent_count += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent_count)
            await asyncio.sleep(self._delay)
            self.concurrent_count -= 1
            yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="ok")
            yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        async def cancel(self, session_id: str) -> None:
            pass

        async def resume(self, session_id: str) -> bool:
            return False

        async def get_info(self):
            return BackendInfo(name=self._name)

        async def close(self) -> None:
            self.closed = True

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self) -> None:
        pool = RuntimePool(max_concurrent=2)
        pool.register("a", RuntimeConfig(backend_type="acp", command="a"))
        backend = self._SlowBackend("a", delay=0.05)

        with patch.object(pool, "get", return_value=backend):
            tasks = [asyncio.create_task(pool.prompt("a", f"task-{i}")) for i in range(4)]
            await asyncio.gather(*tasks)

        assert backend.max_concurrent <= 2


class TestRuntimePoolCancel:
    @pytest.mark.asyncio
    async def test_cancel_calls_backend_cancel(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        mock_backend = MagicMock()
        mock_backend.cancel = AsyncMock()
        pool._backends["claude"] = mock_backend
        await pool.cancel("claude", "sess-1")
        mock_backend.cancel.assert_awaited_once_with("sess-1")

    @pytest.mark.asyncio
    async def test_cancel_noop_for_uninstantiated(self) -> None:
        pool = RuntimePool()
        pool.register("claude", RuntimeConfig(backend_type="acp", command="claude"))
        await pool.cancel("claude", "sess-1")

    @pytest.mark.asyncio
    async def test_cancel_noop_for_unknown(self) -> None:
        pool = RuntimePool()
        await pool.cancel("nonexistent", "sess-1")


class TestRuntimePoolGetConfig:
    def test_returns_config(self) -> None:
        pool = RuntimePool()
        cfg = RuntimeConfig(backend_type="cli", command="claude", max_turns=42, description="test agent")
        pool.register("claude", cfg)
        assert pool.get_config("claude") is cfg
        assert pool.get_config("claude").max_turns == 42
        assert pool.get_config("claude").description == "test agent"

    def test_returns_none_for_unknown(self) -> None:
        pool = RuntimePool()
        assert pool.get_config("nonexistent") is None


class TestRuntimePoolFactory:
    """Tests for _create_runtime factory function and backend_type dispatching."""

    def test_create_acp_runtime(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.pool import _create_runtime

        cfg = RuntimeConfig(backend_type="acp", command="claude")
        rt = _create_runtime("test", cfg)
        assert rt.name == "test"
        assert rt.capabilities.supports_resume is True

    def test_create_cli_runtime(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.pool import _create_runtime

        cfg = RuntimeConfig(backend_type="cli", command="claude")
        rt = _create_runtime("test", cfg)
        assert rt.name == "test"
        assert rt.capabilities.supports_resume is True

    def test_create_cli_runtime_no_resume(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.pool import _create_runtime

        cfg = RuntimeConfig(backend_type="cli", command="codex")
        rt = _create_runtime("test", cfg)
        assert rt.name == "test"
        assert rt.capabilities.supports_resume is False

    def test_create_sdk_runtime(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.pool import _create_runtime

        cfg = RuntimeConfig(backend_type="sdk", command="claude")
        rt = _create_runtime("test", cfg)
        assert rt.name == "test"
        assert rt.capabilities.supports_mcp is True

    def test_unknown_backend_type_raises(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.pool import _create_runtime

        cfg = RuntimeConfig(backend_type="acp", command="test")  # type: ignore[arg-type]
        object.__setattr__(cfg, "backend_type", "unknown_type")
        with pytest.raises(ValueError, match="Unknown backend_type"):
            _create_runtime("test", cfg)


class TestBaseRuntimeTimeout:
    """Tests for BaseRuntime timeout control in run_turn."""

    @pytest.mark.asyncio
    async def test_timeout_yields_error_event(self) -> None:
        class _SlowRuntime(BaseRuntime):
            async def _do_run_turn(self, prompt, session_id, *, mcp_servers=None):
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="start")
                await asyncio.sleep(100)
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="never")

        rt = _SlowRuntime("slow-rt", RuntimeConfig(backend_type="cli", command="x", timeout_seconds=1), "cli")
        events: list[RuntimeEvent] = []
        async for e in rt.run_turn("hello", "s1"):
            events.append(e)

        types = [e.type for e in events]
        assert RuntimeEventType.TEXT_DELTA in types
        assert RuntimeEventType.ERROR in types
        error_event = next(e for e in events if e.type == RuntimeEventType.ERROR)
        assert error_event.data["error"].code == AcpErrorCode.TIMEOUT
        assert error_event.data["error"].retryable is True

    @pytest.mark.asyncio
    async def test_runtime_exception_yields_error_event(self) -> None:
        class _BrokenRuntime(BaseRuntime):
            async def _do_run_turn(self, prompt, session_id, *, mcp_servers=None):
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="before")
                raise RuntimeError("kaboom")

        rt = _BrokenRuntime("broken", RuntimeConfig(backend_type="cli", command="x"), "cli")
        events: list[RuntimeEvent] = []
        async for e in rt.run_turn("hello", "s1"):
            events.append(e)

        types = [e.type for e in events]
        assert RuntimeEventType.TEXT_DELTA in types
        assert RuntimeEventType.ERROR in types
        error_event = next(e for e in events if e.type == RuntimeEventType.ERROR)
        assert error_event.data["error"].code == AcpErrorCode.UNKNOWN
        assert "kaboom" in error_event.data["error"].message


class TestLazyImports:
    """Tests for ACP __init__.py lazy import mechanism."""

    def test_import_runtime_pool(self) -> None:
        from myrm_agent_harness.toolkits.acp import RuntimePool as PoolClass

        assert PoolClass is not None

    def test_import_runtime_config(self) -> None:
        from myrm_agent_harness.toolkits.acp import RuntimeConfig as CfgClass

        assert CfgClass is not None

    def test_import_runtime_backend(self) -> None:
        from myrm_agent_harness.toolkits.acp import RuntimeBackend as BackendProto

        assert BackendProto is not None

    def test_import_unknown_raises(self) -> None:
        import myrm_agent_harness.toolkits.acp as acp_mod

        with pytest.raises(AttributeError, match="has no attribute"):
            _ = acp_mod.NonExistentThing  # type: ignore[attr-defined]

    def test_import_myrm_acp_server(self) -> None:
        from myrm_agent_harness.toolkits.acp import MyrmAcpServer

        assert MyrmAcpServer is not None

    def test_import_run_server(self) -> None:
        from myrm_agent_harness.toolkits.acp import run_server

        assert callable(run_server)


class TestAcpToolsImport:
    """Tests for acp_tools.py module imports."""

    def test_import_acp_tools(self) -> None:
        from myrm_agent_harness.toolkits.acp import (
            MyrmAcpServer,
            RuntimeBackend,
            RuntimeConfig,
            RuntimePool,
            run_server,
        )

        assert RuntimePool is not None
        assert MyrmAcpServer is not None
        assert RuntimeConfig is not None
        assert RuntimeBackend is not None
        assert callable(run_server)


class TestDefaultAgentFactory:
    """Tests for default_factory.py (currently absent from the public toolkit surface)."""

    def test_factory_instantiable(self) -> None:
        default_factory = pytest.importorskip(
            "myrm_agent_harness.toolkits.acp.default_factory",
            reason="default_factory module is opt-in and not bundled by default",
        )
        factory = default_factory.DefaultAgentFactory()
        assert hasattr(factory, "create_agent")


class TestBaseRuntimeStreamTruncation:
    """Tests for BaseRuntime.run_turn streaming truncation (lines 134-151)."""

    @pytest.mark.asyncio
    async def test_truncation_stops_text_but_passes_non_text(self) -> None:
        class _VerboseRuntime(BaseRuntime):
            async def _do_run_turn(self, prompt, session_id, *, mcp_servers=None):
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="x" * 30_000)
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="x" * 30_000)
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="should be dropped")
                yield create_event(RuntimeEventType.TOOL_START, session_id, tool_name="bash")
                yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

        cfg = RuntimeConfig(backend_type="cli", command="x", max_response_chars=50_000)
        rt = _VerboseRuntime("trunc-rt", cfg, "cli")
        events: list[RuntimeEvent] = []
        async for e in rt.run_turn("hello", "s1"):
            events.append(e)

        types = [e.type for e in events]
        text_events = [e for e in events if e.type == RuntimeEventType.TEXT_DELTA]
        assert any("[truncated" in e.data.get("content", "") for e in text_events)
        assert RuntimeEventType.TOOL_START in types
        assert RuntimeEventType.DONE in types
        normal_text = [e for e in text_events if "[truncated" not in e.data.get("content", "")]
        assert len(normal_text) == 1

    @pytest.mark.asyncio
    async def test_cancelled_error_propagated(self) -> None:
        class _CancelledRuntime(BaseRuntime):
            async def _do_run_turn(self, prompt, session_id, *, mcp_servers=None):
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="start")
                raise asyncio.CancelledError

        rt = _CancelledRuntime("cancel-rt", RuntimeConfig(backend_type="cli", command="x"), "cli")
        with pytest.raises(asyncio.CancelledError):
            async for _ in rt.run_turn("hello", "s1"):
                pass

    @pytest.mark.asyncio
    async def test_close_error_suppressed(self) -> None:
        class _FailClose(BaseRuntime):
            async def _do_close(self) -> None:
                raise RuntimeError("close boom")

        rt = _FailClose("fail", RuntimeConfig(backend_type="cli", command="x"), "cli")
        rt._alive = True
        await rt.close()
        assert rt.is_alive is False

    @pytest.mark.asyncio
    async def test_cancel_error_suppressed(self) -> None:
        class _FailCancel(BaseRuntime):
            async def _do_cancel(self, session_id: str) -> None:
                raise RuntimeError("cancel boom")

        rt = _FailCancel("fail", RuntimeConfig(backend_type="cli", command="x"), "cli")
        await rt.cancel("s1")


class TestParserMissingBranches:
    """Tests for _parser.py uncovered branches (lines 73, 129, 172)."""

    def test_parse_error_empty_string_falls_to_message_field(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_error

        event = parse_error({"error": "", "message": "fallback msg"}, "s1")
        assert event.type == RuntimeEventType.ERROR
        assert "fallback msg" in event.data["error"].message

    def test_parse_error_none_falls_to_message_field(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_error

        event = parse_error({"error": None, "message": "from message"}, "s1")
        assert event.type == RuntimeEventType.ERROR
        assert "from message" in event.data["error"].message

    def test_parse_error_none_no_message_uses_default(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_error

        event = parse_error({"error": None}, "s1")
        assert event.type == RuntimeEventType.ERROR
        assert "Unknown error" in event.data["error"].message

    def test_parse_codex_item_reasoning_empty(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_codex_item_event

        event = parse_codex_item_event(
            {"type": "item.completed", "item": {"type": "reasoning", "text": ""}},
            "s1",
        )
        assert event is None

    def test_parse_codex_item_unknown_type(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_codex_item_event

        event = parse_codex_item_event(
            {"type": "item.completed", "item": {"type": "annotation", "text": "foo"}},
            "s1",
        )
        assert event is None

    def test_parse_thinking_empty(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_thinking

        event = parse_thinking({"thinking": ""}, "s1")
        assert event is None

    def test_parse_thinking_with_text_field(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import parse_thinking

        event = parse_thinking({"text": "reasoning content"}, "s1")
        assert event is not None
        assert event.type == RuntimeEventType.REASONING_DELTA
        assert event.data["content"] == "reasoning content"

    def test_extract_text_empty_content_list(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import extract_text_from_event

        result = extract_text_from_event({"content": []})
        assert result is None

    def test_extract_text_non_text_blocks(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime._parser import extract_text_from_event

        result = extract_text_from_event({"content": [{"type": "image", "url": "http://example.com"}]})
        assert result is None


class TestRuntimePoolHealthMonitor:
    """Tests for RuntimePool health monitor integration."""

    @pytest.mark.asyncio
    async def test_start_monitoring_noop_when_disabled(self) -> None:
        pool = RuntimePool()
        await pool.start_monitoring()

    def test_get_health_metrics_empty_when_no_monitor(self) -> None:
        pool = RuntimePool()
        assert pool.get_health_metrics() == {}

    @pytest.mark.asyncio
    async def test_close_all_stops_monitor(self) -> None:
        pool = RuntimePool(enable_health_monitor=True)
        pool.register("test", RuntimeConfig(backend_type="cli", command="echo"))
        await pool.close_all()

    @pytest.mark.asyncio
    async def test_register_with_monitor(self) -> None:
        pool = RuntimePool(enable_health_monitor=True)
        pool.register("test", RuntimeConfig(backend_type="cli", command="echo"))
        _ = pool.get("test")


class TestRuntimePoolRunTurnWithoutBus:
    """Tests for RuntimePool run_turn without event bus."""

    @pytest.mark.asyncio
    async def test_run_turn_no_bus_still_yields_events(self) -> None:
        pool = RuntimePool()
        pool.register("test", RuntimeConfig(backend_type="cli", command="echo"))

        class _SimpleBackend:
            @property
            def name(self) -> str:
                return "test"

            @property
            def capabilities(self):
                return BackendCapabilities()

            @property
            def is_alive(self) -> bool:
                return True

            async def run_turn(self, prompt, session_id, *, mcp_servers=None):
                yield create_event(RuntimeEventType.TEXT_DELTA, session_id, content="hi")
                yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

            async def cancel(self, session_id):
                pass

            async def resume(self, session_id):
                return False

            async def get_info(self):
                return BackendInfo(name="test")

            async def close(self):
                pass

        pool._backends["test"] = _SimpleBackend()
        events = [e async for e in pool.run_turn("test", "task", "s-1")]
        assert len(events) == 2
