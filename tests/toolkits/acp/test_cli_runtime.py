"""Tests for CliRuntime — CLI agent backend with NDJSON parsing."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import CliRuntime
from myrm_agent_harness.toolkits.acp.types import (
    AcpErrorCode,
    RuntimeConfig,
    RuntimeEventType,
)


def _make_config(**overrides: object) -> RuntimeConfig:
    defaults: dict[str, object] = {
        "backend_type": "cli",
        "command": "claude",
        "args": ["--output-format", "stream-json"],
    }
    defaults.update(overrides)
    return RuntimeConfig(**defaults)  # type: ignore[arg-type]


class TestCliRuntimeProperties:
    def test_capabilities_claude(self) -> None:
        rt = CliRuntime("test", _make_config(command="claude"))
        caps = rt.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_resume is True
        assert caps.supports_mcp is False
        assert caps.supports_tools is False

    def test_capabilities_non_resumable(self) -> None:
        rt = CliRuntime("test", _make_config(command="codex"))
        caps = rt.capabilities
        assert caps.supports_streaming is True
        assert caps.supports_resume is False
        assert caps.supports_mcp is False
        assert caps.supports_tools is False

    def test_is_alive_no_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        assert rt.is_alive is False

    def test_name(self) -> None:
        rt = CliRuntime("my-cli", _make_config())
        assert rt.name == "my-cli"


class TestCliRuntimeNdjsonParsing:
    """Test _parse_ndjson_line directly for all event types."""

    def test_text_event(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "assistant", "content": "hello"}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "hello"

    def test_text_event_content_list(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "assistant", "content": [{"type": "text", "text": "hi"}]}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "hi"

    def test_nested_message_content(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "nested"}]}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "nested"

    def test_tool_use_event(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "tool_use", "name": "bash", "input": {"cmd": "ls"}, "id": "tc1"}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_START
        assert event.data["tool_name"] == "bash"

    def test_tool_result_event(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "tool_result", "tool_use_id": "tc1", "content": "ok", "is_error": False}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_RESULT

    def test_result_event_ignored(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "result", "result": "final answer"}),
            "s1",
        )
        assert event is None

    def test_error_event_dict(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "error", "error": {"message": "rate limited"}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_error_event_string(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "error", "error": "something broke"}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_invalid_json_yields_text_delta(self) -> None:
        event = CliRuntime._parse_ndjson_line("not json at all", "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert "not json at all" in event.data["content"]

    def test_non_dict_json_yields_text_delta(self) -> None:
        event = CliRuntime._parse_ndjson_line(json.dumps([1, 2, 3]), "s1")
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA

    def test_unknown_type_returns_none(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "unknown_event", "data": "x"}),
            "s1",
        )
        assert event is None

    def test_empty_content_string(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "assistant", "content": ""}),
            "s1",
        )
        assert event is None

    def test_codex_agent_message(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"id": "0", "msg": {"type": "agent_message", "message": "hello from codex"}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "hello from codex"

    def test_codex_task_started_ignored(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"id": "0", "msg": {"type": "task_started", "model_context_window": None}}),
            "s1",
        )
        assert event is None

    def test_codex_token_count(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"id": "0", "msg": {"type": "token_count", "info": None, "rate_limits": None}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.USAGE_UPDATE

    def test_codex_stream_error(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"id": "0", "msg": {"type": "stream_error", "message": "rate limited"}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_codex_error(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"id": "0", "msg": {"type": "error", "message": "model not supported"}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_codex_init_line_ignored(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"provider": "aliyun", "model": "MiniMax-M2.5", "sandbox": "read-only"}),
            "s1",
        )
        assert event is None

    def test_codex_prompt_line_ignored(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"prompt": "hello"}),
            "s1",
        )
        assert event is None


class TestCodexNewFormatParsing:
    """Tests for Codex new format (item.* / turn.* events)."""

    def test_item_completed_agent_message(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_3", "type": "agent_message", "text": "Done."},
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA
        assert event.data["content"] == "Done."

    def test_item_completed_reasoning(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_0", "type": "reasoning", "text": "Scanning docs..."},
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.REASONING_DELTA
        assert event.data["content"] == "Scanning docs..."

    def test_item_started_command_execution(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.started",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "bash -lc ls",
                        "aggregated_output": "",
                        "exit_code": None,
                        "status": "in_progress",
                    },
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_START
        assert event.data["tool_name"] == "command_execution"
        assert event.data["tool_input"]["command"] == "bash -lc ls"
        assert event.data["tool_call_id"] == "item_1"

    def test_item_completed_command_execution_success(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "bash -lc ls",
                        "aggregated_output": "docs\nsrc\n",
                        "exit_code": 0,
                        "status": "completed",
                    },
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_RESULT
        assert event.data["output"] == "docs\nsrc\n"
        assert event.data["is_error"] is False

    def test_item_completed_command_execution_failed(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_2",
                        "type": "command_execution",
                        "command": "bash -lc false",
                        "aggregated_output": "",
                        "exit_code": 1,
                        "status": "failed",
                    },
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_RESULT
        assert event.data["is_error"] is True

    def test_item_completed_file_change(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_4",
                        "type": "file_change",
                        "changes": [
                            {"path": "docs/new.md", "kind": "add"},
                            {"path": "docs/old.md", "kind": "update"},
                        ],
                        "status": "completed",
                    },
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TOOL_RESULT
        assert "add docs/new.md" in event.data["output"]
        assert "update docs/old.md" in event.data["output"]
        assert event.data["is_error"] is False

    def test_item_completed_error(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_9", "type": "error", "message": "command output truncated"},
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_turn_completed_with_usage(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "turn.completed",
                    "usage": {"input_tokens": 24763, "cached_input_tokens": 24448, "output_tokens": 122},
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.USAGE_UPDATE
        assert event.data["input_tokens"] == 24763
        assert event.data["output_tokens"] == 122
        assert event.data["cache_read"] == 24448

    def test_turn_failed(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "model response stream ended unexpectedly"},
                }
            ),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_thread_started_ignored(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "thread.started", "thread_id": "abc-123"}),
            "s1",
        )
        assert event is None

    def test_turn_started_ignored(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "turn.started"}),
            "s1",
        )
        assert event is None

    def test_item_completed_empty_agent_message(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"id": "item_3", "type": "agent_message", "text": ""},
                }
            ),
            "s1",
        )
        assert event is None

    def test_item_no_item_field(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "item.completed"}),
            "s1",
        )
        assert event is None


class TestCliRuntimeRunTurn:
    @pytest.mark.asyncio
    async def test_requires_command(self) -> None:
        rt = CliRuntime("test", RuntimeConfig(backend_type="cli", command=None))
        with pytest.raises(ValueError, match="requires 'command'"):
            async for _ in rt._do_run_turn("hello", "s1"):
                pass

    @pytest.mark.asyncio
    async def test_successful_run(self) -> None:
        rt = CliRuntime("test", _make_config())
        ndjson_lines = (json.dumps({"type": "assistant", "content": "response"}) + "\n").encode()

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([ndjson_lines])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

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
    async def test_nonzero_exit_with_no_output_emits_error(self) -> None:
        rt = CliRuntime("test", _make_config())

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"fatal error")
        mock_proc.stdin = None

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
    async def test_stdin_prompt_with_p_flag(self) -> None:
        rt = CliRuntime("test", _make_config(args=["-p"]))

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdin.wait_closed = AsyncMock()

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        mock_proc.stdin.write.assert_called()


class TestCliRuntimeCancel:
    @pytest.mark.asyncio
    async def test_cancel_terminates_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        async def fake_wait() -> int:
            mock_proc.returncode = -15
            return -15

        mock_proc.wait = fake_wait
        rt._process = mock_proc

        with patch("myrm_agent_harness.utils.os_compat.os.getpgid", side_effect=lambda x: 12345 if x == 12345 else 99999) as mock_getpgid, patch("myrm_agent_harness.utils.os_compat.os.killpg") as mock_killpg:
            await rt._do_cancel("s1")
            mock_getpgid.assert_any_call(12345)
            mock_killpg.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_kills_on_timeout(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        async def never_finish() -> int:
            await asyncio.sleep(100)
            return 0

        mock_proc.wait = never_finish
        rt._process = mock_proc

        with patch("myrm_agent_harness.utils.os_compat.os.getpgid", side_effect=lambda x: 12345 if x == 12345 else 99999), patch("myrm_agent_harness.utils.os_compat.os.killpg") as mock_killpg:
            await rt._do_cancel("s1")
            assert mock_killpg.call_count == 2

    @pytest.mark.asyncio
    async def test_cancel_noop_when_no_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        await rt._do_cancel("s1")


class TestCliRuntimeStatus:
    @pytest.mark.asyncio
    async def test_status_stopped_no_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        assert await rt._do_get_status() == "stopped"

    @pytest.mark.asyncio
    async def test_status_ready_running(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        rt._process = mock_proc
        assert await rt._do_get_status() == "ready"

    @pytest.mark.asyncio
    async def test_status_error_nonzero_exit(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        rt._process = mock_proc
        assert await rt._do_get_status() == "error"

    @pytest.mark.asyncio
    async def test_status_stopped_zero_exit(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        rt._process = mock_proc
        assert await rt._do_get_status() == "stopped"


class TestCliRuntimeClose:
    @pytest.mark.asyncio
    async def test_close_clears_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        rt._process = mock_proc
        await rt._do_close()
        assert rt._process is None


class TestCliRuntimeMaxTurnsLayer1:
    """Tests for CLI --max-turns argument injection (Layer 1)."""

    @pytest.mark.asyncio
    async def test_claude_gets_max_turns_arg(self) -> None:
        rt = CliRuntime("test", _make_config(max_turns=10))
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        captured_args: list[object] = []

        async def capture_exec(*args, **kwargs):
            captured_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        assert "--max-turns" in captured_args
        assert "10" in captured_args

    @pytest.mark.asyncio
    async def test_non_claude_skips_max_turns(self) -> None:
        rt = CliRuntime(
            "test",
            RuntimeConfig(
                backend_type="cli",
                command="codex",
                args=["--some-flag"],
                max_turns=10,
            ),
        )
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        captured_args: list[object] = []

        async def capture_exec(*args, **kwargs):
            captured_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        assert "--max-turns" not in captured_args

    @pytest.mark.asyncio
    async def test_max_turns_zero_skips_arg(self) -> None:
        rt = CliRuntime("test", _make_config(max_turns=0))
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        captured_args: list[object] = []

        async def capture_exec(*args, **kwargs):
            captured_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        assert "--max-turns" not in captured_args


class TestSupportsMaxTurns:
    """Tests for the _supports_max_turns helper function."""

    def test_claude_supported(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import _supports_max_turns

        assert _supports_max_turns("claude") is True
        assert _supports_max_turns("/usr/local/bin/claude") is True

    def test_codex_not_supported(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import _supports_max_turns

        assert _supports_max_turns("codex") is False

    def test_gemini_not_supported(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import _supports_max_turns

        assert _supports_max_turns("gemini") is False

    def test_arbitrary_command_not_supported(self) -> None:
        from myrm_agent_harness.toolkits.acp.runtime.cli_runtime import _supports_max_turns

        assert _supports_max_turns("/opt/custom/agent") is False


class TestCliRuntimeSessionResume:
    """Tests for session ID capture and --resume injection."""

    @pytest.mark.asyncio
    async def test_captures_session_id_from_result(self) -> None:
        rt = CliRuntime("test", _make_config())
        result_line = json.dumps({"type": "result", "session_id": "cli-sess-abc"})
        ndjson_lines = (result_line + "\n").encode()

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([ndjson_lines])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        assert rt._cli_session_ids.get("s1") == "cli-sess-abc"

    @pytest.mark.asyncio
    async def test_resume_injects_flag(self) -> None:
        rt = CliRuntime("test", _make_config())
        rt._cli_session_ids["s1"] = "cli-sess-abc"

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        captured_args: list[object] = []

        async def capture_exec(*args, **kwargs):
            captured_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        assert "--resume" in captured_args
        assert "cli-sess-abc" in captured_args

    @pytest.mark.asyncio
    async def test_do_resume_returns_true_when_session_exists(self) -> None:
        rt = CliRuntime("test", _make_config())
        rt._cli_session_ids["s1"] = "cli-sess-abc"
        assert await rt._do_resume("s1") is True

    @pytest.mark.asyncio
    async def test_do_resume_returns_false_when_no_session(self) -> None:
        rt = CliRuntime("test", _make_config())
        assert await rt._do_resume("s1") is False

    def test_is_alive_with_running_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        rt._process = mock_proc
        assert rt.is_alive is True

    def test_is_alive_with_finished_process(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        rt._process = mock_proc
        assert rt.is_alive is False


class TestCliRuntimeVerboseAndPrompt:
    """Tests for --verbose injection and stdin vs positional prompt."""

    @pytest.mark.asyncio
    async def test_verbose_injected_for_stream_json(self) -> None:
        rt = CliRuntime("test", _make_config(args=["--output-format", "stream-json"]))

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        captured_args: list[object] = []

        async def capture_exec(*args, **kwargs):
            captured_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            _ = [e async for e in rt._do_run_turn("hello", "s1")]

        assert "--verbose" in captured_args

    @pytest.mark.asyncio
    async def test_prompt_appended_as_positional_when_no_p_flag(self) -> None:
        rt = CliRuntime("test", _make_config(args=["--output-format", "stream-json"]))

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        captured_args: list[object] = []

        async def capture_exec(*args, **kwargs):
            captured_args.extend(args)
            return mock_proc

        with patch("asyncio.create_subprocess_exec", side_effect=capture_exec):
            _ = [e async for e in rt._do_run_turn("my prompt text", "s1")]

        assert "my prompt text" in captured_args

    @pytest.mark.asyncio
    async def test_nonzero_exit_with_text_logs_warning(self) -> None:
        rt = CliRuntime("test", _make_config())
        ndjson_lines = (json.dumps({"type": "assistant", "content": "partial"}) + "\n").encode()

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([ndjson_lines])
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"some warning")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 1
            return 1

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events = [e async for e in rt._do_run_turn("hello", "s1")]

        types = [e.type for e in events]
        assert RuntimeEventType.TEXT_DELTA in types
        assert RuntimeEventType.DONE in types

    @pytest.mark.asyncio
    async def test_process_none_after_cancel(self) -> None:
        rt = CliRuntime("test", _make_config())
        ndjson = (json.dumps({"type": "assistant", "content": "hi"}) + "\n").encode()

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter([ndjson])
        mock_proc.stdin = None

        async def drain_and_nullify() -> bytes:
            rt._process = None
            return b""

        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = drain_and_nullify

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events = [e async for e in rt._do_run_turn("hello", "s1")]

        types = [e.type for e in events]
        assert RuntimeEventType.STATUS_UPDATE in types
        assert RuntimeEventType.TEXT_DELTA in types
        assert RuntimeEventType.DONE not in types


class TestCliRuntimeCancelWindows:
    """Tests for _do_cancel Windows fallback path."""

    @pytest.mark.asyncio
    async def test_cancel_windows_uses_terminate(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        async def fake_wait() -> int:
            mock_proc.returncode = -15
            return -15

        mock_proc.wait = fake_wait
        rt._process = mock_proc

        with patch("myrm_agent_harness.utils.os_compat.IS_WIN", True), patch("myrm_agent_harness.utils.os_compat.subprocess.run") as mock_run:
            await rt._do_cancel("s1")
        mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_process_lookup_error(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345

        async def fake_wait() -> int:
            mock_proc.returncode = -15
            return -15

        mock_proc.wait = fake_wait
        rt._process = mock_proc

        with patch("myrm_agent_harness.utils.os_compat.os.getpgid", side_effect=ProcessLookupError):
            await rt._do_cancel("s1")

    @pytest.mark.asyncio
    async def test_cancel_already_finished(self) -> None:
        rt = CliRuntime("test", _make_config())
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        rt._process = mock_proc
        await rt._do_cancel("s1")


class TestCliRuntimeEmptyLines:
    """Test that empty lines in stdout are skipped."""

    @pytest.mark.asyncio
    async def test_empty_lines_skipped(self) -> None:
        rt = CliRuntime("test", _make_config())
        lines = [b"\n", b"  \n", json.dumps({"type": "assistant", "content": "ok"}).encode() + b"\n"]

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.stdout.__aiter__ = lambda self: aiter(lines)
        mock_proc.stderr = AsyncMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")
        mock_proc.stdin = None

        async def fake_wait() -> int:
            mock_proc.returncode = 0
            return 0

        mock_proc.wait = fake_wait

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            events = [e async for e in rt._do_run_turn("hello", "s1")]

        text_events = [e for e in events if e.type == RuntimeEventType.TEXT_DELTA]
        assert len(text_events) == 1
        assert text_events[0].data["content"] == "ok"


class TestCliRuntimeNdjsonEdgeCases:
    """Additional NDJSON parsing edge cases."""

    def test_usage_event_with_info_field(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "usage", "info": {"input_tokens": 500, "output_tokens": 200}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.USAGE_UPDATE
        assert event.data["input_tokens"] == 500

    def test_usage_event_without_info(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "usage", "input_tokens": 100, "output_tokens": 50}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.USAGE_UPDATE

    def test_text_event_type(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "text", "content": "hello"}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.TEXT_DELTA

    def test_result_event_with_usage(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "result", "usage": {"input_tokens": 1000, "output_tokens": 300}}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.USAGE_UPDATE

    def test_turn_completed_without_usage(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "turn.completed"}),
            "s1",
        )
        assert event is None

    def test_turn_failed_no_error_object(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "turn.failed"}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.ERROR

    def test_agent_message_empty(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "agent_message", "message": ""}),
            "s1",
        )
        assert event is None

    def test_thinking_event(self) -> None:
        event = CliRuntime._parse_ndjson_line(
            json.dumps({"type": "thinking", "thinking": "hmm let me think"}),
            "s1",
        )
        assert event is not None
        assert event.type == RuntimeEventType.REASONING_DELTA

    def test_capture_session_id_non_json(self) -> None:
        rt = CliRuntime("test", _make_config())
        rt._capture_cli_session_id("not json", "s1")
        assert "s1" not in rt._cli_session_ids

    def test_capture_session_id_non_result(self) -> None:
        rt = CliRuntime("test", _make_config())
        rt._capture_cli_session_id(json.dumps({"type": "text"}), "s1")
        assert "s1" not in rt._cli_session_ids

    def test_capture_session_id_empty_session(self) -> None:
        rt = CliRuntime("test", _make_config())
        rt._capture_cli_session_id(json.dumps({"type": "result", "session_id": ""}), "s1")
        assert "s1" not in rt._cli_session_ids


async def aiter(items: list[bytes]) -> asyncio.StreamReader:
    """Helper to create an async iterator from a list of byte lines."""
    for item in items:
        yield item  # type: ignore[misc]
