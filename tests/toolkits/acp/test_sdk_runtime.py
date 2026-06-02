"""Tests for SdkRuntime — SDK bridge backend with NDJSON event parsing."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.runtime.sdk_runtime import SdkRuntime
from myrm_agent_harness.toolkits.acp.types import (
    AcpErrorCode,
    McpServerConfig,
    RuntimeConfig,
    RuntimeEventType,
)


def _make_config(**overrides: object) -> RuntimeConfig:
    defaults: dict[str, object] = {"backend_type": "sdk", "command": "claude"}
    defaults.update(overrides)
    return RuntimeConfig(**defaults)  # type: ignore[arg-type]


class TestSdkRuntimeProperties:
    def test_capabilities(self) -> None:
        rt = SdkRuntime("test", _make_config())
        caps = rt.capabilities
        assert caps.supports_resume is True
        assert caps.supports_mcp is True
        assert caps.supports_streaming is True
        assert caps.supports_tools is True

    def test_is_alive_no_process(self) -> None:
        rt = SdkRuntime("test", _make_config())
        assert rt.is_alive is False

    def test_name(self) -> None:
        rt = SdkRuntime("my-sdk", _make_config())
        assert rt.name == "my-sdk"


class TestSdkRuntimeEventParsing:
    """Test _parse_sdk_event directly for all event types."""

    def test_text_event(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "text", "text": "hello"}), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "hello"

    def test_assistant_event(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "assistant", "content": "hi"}), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA

    def test_content_block_delta(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "content_block_delta", "text": "chunk"}), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA

    def test_thinking_event(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "thinking", "text": "reasoning..."}), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.REASONING_DELTA

    def test_thinking_empty_returns_none(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "thinking", "text": ""}), "s1")
        assert event is None

    def test_tool_use_event(self) -> None:
        event = SdkRuntime._parse_sdk_event(
            json.dumps({"type": "tool_use", "name": "bash", "input": {}, "id": "tc1"}), "s1"
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_START
        assert event.data["tool_name"] == "bash"

    def test_tool_result_event(self) -> None:
        event = SdkRuntime._parse_sdk_event(
            json.dumps({"type": "tool_result", "tool_use_id": "tc1", "content": "ok"}), "s1"
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_RESULT

    def test_usage_event(self) -> None:
        event = SdkRuntime._parse_sdk_event(
            json.dumps(
                {
                    "type": "usage",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 10,
                    "cache_creation_input_tokens": 5,
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.USAGE_UPDATE
        assert event.data["input_tokens"] == 100

    def test_error_event_dict(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "error", "error": {"message": "bad request"}}), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_error_event_string(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "error", "error": "something broke"}), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_invalid_json_returns_text_delta(self) -> None:
        event = SdkRuntime._parse_sdk_event("not json", "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA

    def test_non_dict_json(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps(42), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA

    def test_unknown_type_returns_none(self) -> None:
        event = SdkRuntime._parse_sdk_event(json.dumps({"type": "unknown_event"}), "s1")
        assert event is None


class TestSdkRuntimeRunTurn:
    @pytest.mark.asyncio
    async def test_successful_run(self) -> None:
        rt = SdkRuntime("test", _make_config())
        ndjson_lines = (json.dumps({"type": "text", "text": "answer"}) + "\n").encode()

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: _aiter([ndjson_lines])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events = [e async for e in rt._do_run_turn("hello", "s1")]

        types = [e.type for e in events]
        assert RuntimeEventType.STATUS_UPDATE in types
        assert RuntimeEventType.TEXT_DELTA in types
        assert RuntimeEventType.DONE in types

    @pytest.mark.asyncio
    async def test_mcp_servers_passed_in_payload(self) -> None:
        rt = SdkRuntime("test", _make_config())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: _aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        mcp = [McpServerConfig(name="test-mcp", command="node", args=["server.js"])]

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            [e async for e in rt._do_run_turn("hello", "s1", mcp_servers=mcp)]

        written = b"".join(call.args[0] for call in mock_proc.stdin.write.call_args_list)
        payload = json.loads(written.split(b"\n")[0])
        assert "mcp_servers" in payload

    @pytest.mark.asyncio
    async def test_nonzero_exit_no_output_emits_error(self) -> None:
        rt = SdkRuntime("test", _make_config())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: _aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"crash")
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()

        async def fake_wait() -> int:
            mock_proc.returncode = 1
            return 1

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events = [e async for e in rt._do_run_turn("hello", "s1")]

        error_events = [e for e in events if e.type == RuntimeEventType.ERROR]
        assert len(error_events) == 1
        assert error_events[0].data["error"].code == AcpErrorCode.PROCESS_CRASHED

    @pytest.mark.asyncio
    async def test_default_command_is_claude(self) -> None:
        rt = SdkRuntime("test", RuntimeConfig(backend_type="sdk", command=None))

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: _aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
            [e async for e in rt._do_run_turn("hello", "s1")]

        assert mock_exec.call_args[0][0] == "claude"


class TestSdkRuntimeCancel:
    @pytest.mark.asyncio
    async def test_cancel_terminates(self) -> None:
        rt = SdkRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()

        async def fake_wait() -> int:
            mock_proc.returncode = -15
            return -15

        mock_proc.wait = fake_wait
        rt._process = mock_proc

        await rt._do_cancel("s1")
        mock_proc.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_kills_on_timeout(self) -> None:
        rt = SdkRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.terminate = MagicMock()
        mock_proc.kill = MagicMock()

        async def never_finish() -> int:
            await asyncio.sleep(100)
            return 0

        mock_proc.wait = never_finish
        rt._process = mock_proc

        await rt._do_cancel("s1")
        mock_proc.kill.assert_called_once()


class TestSdkRuntimeStatus:
    @pytest.mark.asyncio
    async def test_status_stopped(self) -> None:
        rt = SdkRuntime("test", _make_config())
        assert await rt._do_get_status() == "stopped"

    @pytest.mark.asyncio
    async def test_status_ready(self) -> None:
        rt = SdkRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        rt._process = mock_proc
        assert await rt._do_get_status() == "ready"

    @pytest.mark.asyncio
    async def test_status_error(self) -> None:
        rt = SdkRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        rt._process = mock_proc
        assert await rt._do_get_status() == "error"


class TestSdkRuntimeClose:
    @pytest.mark.asyncio
    async def test_close_clears_process(self) -> None:
        rt = SdkRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        rt._process = mock_proc
        await rt._do_close()
        assert rt._process is None


async def _aiter(items: list[bytes]) -> asyncio.StreamReader:
    for item in items:
        yield item  # type: ignore[misc]
