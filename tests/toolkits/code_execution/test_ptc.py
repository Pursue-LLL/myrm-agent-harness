"""Tests for Programmatic Tool Calling (PTC) subsystem.

Covers: models, security, helpers, stub_generator, dispatcher, rpc_server,
and the ptc_injection E2E flow.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys

import pytest
from langchain_core.tools import tool as lc_tool
from pydantic import ValidationError

from myrm_agent_harness.toolkits.code_execution.ptc.dispatcher import PtcDispatcher
from myrm_agent_harness.toolkits.code_execution.ptc.helpers import HELPERS_SOURCE
from myrm_agent_harness.toolkits.code_execution.ptc.models import (
    PtcConfig,
    PtcExecutionTrace,
    PtcRpcRequest,
    PtcRpcResponse,
    PtcToolCallRecord,
)
from myrm_agent_harness.toolkits.code_execution.ptc.rpc_server import PtcRpcServer
from myrm_agent_harness.toolkits.code_execution.ptc.security import (
    TERMINAL_BLOCKED_PARAMS,
    scrub_child_env,
)
from myrm_agent_harness.toolkits.code_execution.ptc.stub_generator import (
    generate_stubs,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@lc_tool
def mock_file_read(path: str) -> str:
    """Read a file at given path."""
    return f"content_of_{path}"


@lc_tool
def mock_grep(pattern: str, path: str = ".") -> str:
    """Search for pattern in path."""
    return f"found_{pattern}_in_{path}"


@lc_tool
def mock_bash(command: str) -> str:
    """Execute a bash command."""
    return f"output_of_{command}"


@lc_tool
def mock_orchestration(task_id: str, optional_note: str = "") -> dict:
    """Orchestration-style tool returning a structured dict, like DW primitives."""
    return {"success": True, "task_id": task_id, "note": optional_note, "result": f"done_{task_id}"}


# ---------------------------------------------------------------------------
# models.py tests
# ---------------------------------------------------------------------------


class TestPtcConfig:
    def test_defaults(self):
        config = PtcConfig()
        assert config.max_tool_calls == 50
        assert config.timeout_seconds == 300
        assert config.max_output_chars == 200_000

    def test_custom_values(self):
        config = PtcConfig(max_tool_calls=100, timeout_seconds=60, max_output_chars=4096)
        assert config.max_tool_calls == 100
        assert config.max_output_chars == 4096

    def test_validation_boundaries(self):
        with pytest.raises(ValidationError):
            PtcConfig(max_tool_calls=0)
        with pytest.raises(ValidationError):
            PtcConfig(max_tool_calls=201)
        with pytest.raises(ValidationError):
            PtcConfig(timeout_seconds=5)


class TestPtcRpcRequest:
    def test_basic(self):
        req = PtcRpcRequest(tool="file_read", args={"path": "/tmp/x"})
        assert req.tool == "file_read"
        assert req.args == {"path": "/tmp/x"}

    def test_serialization_roundtrip(self):
        req = PtcRpcRequest(tool="grep", args={"pattern": "hello"})
        data = req.model_dump_json()
        restored = PtcRpcRequest.model_validate_json(data)
        assert restored == req


class TestPtcRpcResponse:
    def test_success(self):
        resp = PtcRpcResponse(result="ok")
        assert resp.result == "ok"
        assert resp.error is None

    def test_error(self):
        resp = PtcRpcResponse(error="not found")
        assert resp.result is None
        assert resp.error == "not found"


class TestPtcToolCallRecord:
    def test_basic(self):
        rec = PtcToolCallRecord(tool="bash", args_preview='{"cmd":"ls"}', duration_ms=1.5, success=True)
        assert rec.success is True
        assert rec.error is None


class TestPtcExecutionTrace:
    def test_defaults(self):
        trace = PtcExecutionTrace(script_preview="print('hi')")
        assert trace.tool_calls == []
        assert trace.total_duration_ms == 0.0
        assert trace.exit_code is None


# ---------------------------------------------------------------------------
# security.py tests
# ---------------------------------------------------------------------------


class TestScrubChildEnv:
    def test_removes_secrets(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "API_KEY": "secret123",
            "AWS_SECRET_ACCESS_KEY": "aws_secret",
            "OPENAI_API_KEY": "sk-xxx",
            "MYRM_TOKEN": "myrm123",
        }
        result = scrub_child_env(env)
        assert "PATH" in result
        assert "HOME" in result
        assert "API_KEY" not in result
        assert "AWS_SECRET_ACCESS_KEY" not in result
        assert "OPENAI_API_KEY" not in result
        assert "MYRM_TOKEN" not in result

    def test_preserves_safe_prefixes(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/root",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "C",
            "TMPDIR": "/tmp",
            "XDG_RUNTIME_DIR": "/run/user/1000",
        }
        result = scrub_child_env(env)
        for key in env:
            assert key in result

    def test_adds_python_flags(self):
        result = scrub_child_env({})
        assert result["PYTHONDONTWRITEBYTECODE"] == "1"
        assert result["PYTHONIOENCODING"] == "utf-8"
        assert result["PYTHONUTF8"] == "1"

    def test_terminal_blocked_params_defined(self):
        assert "background" in TERMINAL_BLOCKED_PARAMS
        assert "pty" in TERMINAL_BLOCKED_PARAMS


# ---------------------------------------------------------------------------
# helpers.py tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_helpers_source_contains_functions(self):
        assert "def json_parse" in HELPERS_SOURCE
        assert "def shell_quote" in HELPERS_SOURCE
        assert "def retry" in HELPERS_SOURCE
        assert "def path_join" in HELPERS_SOURCE

    def test_helpers_source_is_valid_python(self):
        compile(HELPERS_SOURCE, "<helpers>", "exec")

    def test_helpers_shell_quote_runtime_execution(self):
        namespace: dict = {}
        exec(  # noqa: S102
            "import json, os, time, sys, shlex, re\n" + HELPERS_SOURCE,
            namespace,
        )
        fn_shell_quote = namespace["shell_quote"]
        assert fn_shell_quote("") in ("''", '""')
        assert fn_shell_quote("normal_arg") in ("normal_arg", "'normal_arg'")
        assert "hello" in fn_shell_quote("hello world")



# ---------------------------------------------------------------------------
# stub_generator.py tests
# ---------------------------------------------------------------------------


class TestStubGenerator:
    def test_generates_valid_python(self):
        source = generate_stubs([mock_file_read, mock_grep])
        compile(source, "<stubs>", "exec")

    def test_contains_tool_functions(self):
        source = generate_stubs([mock_file_read, mock_grep, mock_bash])
        assert "def mock_file_read(" in source
        assert "def mock_grep(" in source
        assert "def mock_bash(" in source

    def test_contains_helpers(self):
        source = generate_stubs([mock_file_read])
        assert "def json_parse" in source
        assert "def shell_quote" in source

    def test_contains_rpc_call(self):
        source = generate_stubs([mock_file_read])
        assert "_rpc_call" in source
        assert "_MYRM_PTC_SOCKET" in source

    def test_tcp_fallback_variant(self):
        source = generate_stubs([mock_file_read], use_tcp_fallback=True)
        assert "_MYRM_PTC_PORT" in source
        assert "AF_INET" in source

    def test_all_list(self):
        source = generate_stubs([mock_file_read, mock_grep])
        assert '"mock_file_read"' in source
        assert '"mock_grep"' in source
        assert "__all__" in source

    def test_empty_tools(self):
        source = generate_stubs([])
        compile(source, "<empty_stubs>", "exec")
        assert "__all__ = []" in source


# ---------------------------------------------------------------------------
# dispatcher.py tests
# ---------------------------------------------------------------------------


class TestPtcDispatcher:
    def test_tools_property(self):
        dispatcher = PtcDispatcher([mock_file_read, mock_grep])
        tools = dispatcher.tools
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "mock_file_read" in names
        assert "mock_grep" in names

    def test_records_property_initially_empty(self):
        dispatcher = PtcDispatcher([mock_file_read])
        assert dispatcher.records == []

    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        dispatcher = PtcDispatcher([mock_file_read])
        req = PtcRpcRequest(tool="mock_file_read", args={"path": "/tmp/x"})
        resp = await dispatcher.dispatch(req)
        assert resp.error is None
        assert "content_of_/tmp/x" in resp.result
        assert len(dispatcher.records) == 1
        assert dispatcher.records[0].success is True

    @pytest.mark.asyncio
    async def test_dispatch_preserves_dict_payload(self):
        """Structured tool results must survive the wire as dicts, not repr strings.

        Regression guard for the DW contract tear: prompts.py declares every
        myrm_tools primitive as ``-> dict`` and few-shot examples unpack them
        (``**result`` / ``answers["results"]``). Serializing to a string makes
        those scripts fail with TypeError at runtime.
        """
        dispatcher = PtcDispatcher([mock_orchestration])
        req = PtcRpcRequest(tool="mock_orchestration", args={"task_id": "t1"})
        resp = await dispatcher.dispatch(req)
        assert resp.error is None
        assert resp.result == {"success": True, "task_id": "t1", "note": "", "result": "done_t1"}

    @pytest.mark.asyncio
    async def test_dispatch_keeps_plain_string_result(self):
        """String results stay strings so existing string-only tools are unaffected."""
        dispatcher = PtcDispatcher([mock_file_read])
        resp = await dispatcher.dispatch(PtcRpcRequest(tool="mock_file_read", args={"path": "/y"}))
        assert resp.error is None
        assert resp.result == "content_of_/y"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool(self):
        dispatcher = PtcDispatcher([mock_file_read])
        req = PtcRpcRequest(tool="nonexistent", args={})
        resp = await dispatcher.dispatch(req)
        assert resp.error is not None
        assert "Unknown tool" in resp.error
        assert dispatcher.records[0].success is False

    @pytest.mark.asyncio
    async def test_dispatch_blocked_tool(self):
        dispatcher = PtcDispatcher([mock_file_read])
        req = PtcRpcRequest(tool="execute_code", args={"script": "x"})
        resp = await dispatcher.dispatch(req)
        assert resp.error is not None
        assert "not callable from PTC" in resp.error

    @pytest.mark.asyncio
    async def test_terminal_param_filtering(self):
        @lc_tool
        def terminal(command: str, background: bool = False) -> str:
            """Run terminal command."""
            return f"ran: {command}, bg={background}"

        dispatcher = PtcDispatcher([terminal])
        req = PtcRpcRequest(tool="terminal", args={"command": "ls", "background": True})
        resp = await dispatcher.dispatch(req)
        assert resp.error is None
        assert "bg=True" not in (resp.result or "")


# ---------------------------------------------------------------------------
# rpc_server.py tests
# ---------------------------------------------------------------------------


class TestPtcRpcServer:
    def test_dispatcher_property(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(), dispatcher)
        assert server.dispatcher is dispatcher

    def test_call_count_initially_zero(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(), dispatcher)
        assert server.call_count == 0

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(), dispatcher)
        await server.start()
        assert server.socket_path != "" or server.tcp_port != 0
        await server.stop()

    @pytest.mark.asyncio
    async def test_get_child_env_uds(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(), dispatcher)
        await server.start()
        try:
            env = server.get_child_env()
            if sys.platform != "win32":
                assert "_MYRM_PTC_SOCKET" in env
                assert env["_MYRM_PTC_SOCKET"] != ""
            assert "_MYRM_PTC_TIMEOUT" in env
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_rpc_roundtrip(self):
        """Full RPC roundtrip: client -> server -> dispatcher -> response."""
        dispatcher = PtcDispatcher([mock_file_read])
        config = PtcConfig(timeout_seconds=10)
        server = PtcRpcServer(config, dispatcher)
        await server.start()

        try:
            req = PtcRpcRequest(tool="mock_file_read", args={"path": "/a/b"}, auth_token=server.auth_token)
            payload = req.model_dump_json().encode("utf-8")
            header = struct.pack("!I", len(payload))

            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(header + payload)
            await writer.drain()

            resp_header = await asyncio.wait_for(reader.readexactly(4), timeout=5)
            resp_len = struct.unpack("!I", resp_header)[0]
            resp_data = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
            writer.close()
            await writer.wait_closed()

            resp = json.loads(resp_data)
            assert resp.get("error") is None
            assert "content_of_/a/b" in resp["result"]
            assert server.call_count == 1
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_tool_call_limit(self):
        """Server enforces max_tool_calls limit."""
        dispatcher = PtcDispatcher([mock_file_read])
        config = PtcConfig(max_tool_calls=2, timeout_seconds=10)
        server = PtcRpcServer(config, dispatcher)
        await server.start()

        try:
            for i in range(3):
                req = PtcRpcRequest(
                    tool="mock_file_read", args={"path": f"/{i}"}, auth_token=server.auth_token
                )
                payload = req.model_dump_json().encode("utf-8")
                header = struct.pack("!I", len(payload))

                reader, writer = await asyncio.open_unix_connection(server.socket_path)
                writer.write(header + payload)
                await writer.drain()

                resp_header = await asyncio.wait_for(reader.readexactly(4), timeout=5)
                resp_len = struct.unpack("!I", resp_header)[0]
                resp_data = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
                writer.close()
                await writer.wait_closed()

                resp = json.loads(resp_data)
                if i < 2:
                    assert resp.get("error") is None
                else:
                    assert "limit reached" in resp.get("error", "")
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_tcp_mode_lifecycle(self):
        """Server can start/stop in TCP mode and provides correct env."""
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(), dispatcher)
        server._use_tcp = True
        await server.start()
        try:
            assert server.tcp_port > 0
            env = server.get_child_env()
            assert "_MYRM_PTC_PORT" in env
            assert int(env["_MYRM_PTC_PORT"]) == server.tcp_port
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_tcp_mode_roundtrip(self):
        """Full RPC roundtrip over TCP."""
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        server._use_tcp = True
        await server.start()
        try:
            req = PtcRpcRequest(
                tool="mock_file_read", args={"path": "/tcp"}, auth_token=server.auth_token
            )
            payload = req.model_dump_json().encode("utf-8")
            header = struct.pack("!I", len(payload))

            reader, writer = await asyncio.open_connection("127.0.0.1", server.tcp_port)
            writer.write(header + payload)
            await writer.drain()

            resp_header = await asyncio.wait_for(reader.readexactly(4), timeout=5)
            resp_len = struct.unpack("!I", resp_header)[0]
            resp_data = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
            writer.close()
            await writer.wait_closed()

            resp = json.loads(resp_data)
            assert resp.get("error") is None
            assert "content_of_/tcp" in resp["result"]
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_oversized_request_rejected(self):
        """Server rejects requests claiming > 10MB payload."""
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            fake_header = struct.pack("!I", 11 * 1024 * 1024)
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(fake_header)
            await writer.drain()

            resp_header = await asyncio.wait_for(reader.readexactly(4), timeout=5)
            resp_len = struct.unpack("!I", resp_header)[0]
            resp_data = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
            writer.close()
            await writer.wait_closed()

            resp = json.loads(resp_data)
            assert "too large" in resp.get("error", "").lower()
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_malformed_json_request(self):
        """Server returns error for invalid JSON payload."""
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            bad_payload = b"not-valid-json!!!"
            header = struct.pack("!I", len(bad_payload))

            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(header + bad_payload)
            await writer.drain()

            resp_header = await asyncio.wait_for(reader.readexactly(4), timeout=5)
            resp_len = struct.unpack("!I", resp_header)[0]
            resp_data = await asyncio.wait_for(reader.readexactly(resp_len), timeout=5)
            writer.close()
            await writer.wait_closed()

            resp = json.loads(resp_data)
            assert "Invalid request" in resp.get("error", "")
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_client_disconnect_handled(self):
        """Server handles client disconnection without crashing."""
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            _reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(0.1)
        finally:
            await server.stop()


# ---------------------------------------------------------------------------
# ptc_injection.py E2E tests
# ---------------------------------------------------------------------------


class TestPtcInjection:
    """Tests for inject_ptc_for_python_execution (bash Python PTC path)."""

    @pytest.mark.asyncio
    async def test_basic_script_execution(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        context = ExecutionContext(code="print('hello world')", timeout=30)
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        assert result.success
        assert "hello world" in (result.stdout or "")

    @pytest.mark.asyncio
    async def test_tool_call_from_script(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        script = 'import myrm_tools\nresult = myrm_tools.mock_file_read(path="/test/file.txt")\nprint(result)'
        context = ExecutionContext(code=script, timeout=30)
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        assert result.success
        assert "content_of_/test/file.txt" in (result.stdout or "")

    @pytest.mark.asyncio
    async def test_dict_contract_end_to_end(self):
        """Real subprocess + real stub generator + real RPC server: dict survives.

        This is the unpatched E2E guard. Mocked dispatcher tests cannot catch a
        ``str`` vs ``dict`` regression because both satisfy ``assert x in stdout``;
        only a script that actually unpacks the dict proves the wire contract.
        """
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        script = (
            "import myrm_tools\n"
            'result = myrm_tools.mock_orchestration(task_id="t7", optional_note="")\n'
            'print("TYPE", type(result).__name__)\n'
            'print("MERGED", {**result}["task_id"])\n'
            'print("SUBSCRIPT", result["result"])\n'
            'print("GET", result.get("success"))\n'
            'print("EMPTY_KEPT", "note" in result and result["note"] == "")\n'
        )
        context = ExecutionContext(code=script, timeout=30)
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_orchestration])

        assert result.success, f"script failed: {result.stderr}"
        out = result.stdout or ""
        assert "TYPE dict" in out
        assert "MERGED t7" in out
        assert "SUBSCRIPT done_t7" in out
        assert "GET True" in out
        assert "EMPTY_KEPT True" in out

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        script = (
            "import myrm_tools\n"
            'r1 = myrm_tools.mock_file_read(path="/a")\n'
            'r2 = myrm_tools.mock_grep(pattern="hello", path="/b")\n'
            'print(f"read: {r1}")\n'
            'print(f"grep: {r2}")'
        )
        context = ExecutionContext(code=script, timeout=30)
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_file_read, mock_grep])
        assert result.success
        assert "content_of_/a" in (result.stdout or "")
        assert "found_hello_in_/b" in (result.stdout or "")

    @pytest.mark.asyncio
    async def test_script_error_returns_stderr(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        context = ExecutionContext(code="raise ValueError('test error')", timeout=30)
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        assert not result.success
        assert "ValueError" in (result.stderr or "")

    @pytest.mark.asyncio
    async def test_bash_executor_python_skips_turn1_ptc_injection(self):
        """BashExecutor routes Python to plain CodeExecutor.execute (no Turn1 stub RPC)."""
        from myrm_agent_harness.agent.meta_tools.bash._executor.executor import (
            BashExecutor,
        )
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        inner_executor = InProcessExecutor()
        BashExecutor(executor=inner_executor, enable_skill_execution=False)

        context = ExecutionContext(
            code="print('plain')",
            original_code="print('plain')",
            session_id="sess",
            timeout=30,
        )
        result = await inner_executor.execute(context)
        assert result.success
        assert "plain" in (result.stdout or "")

    @pytest.mark.asyncio
    async def test_helpers_available_in_script(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        script = (
            "import myrm_tools\n"
            'result = myrm_tools.json_parse(\'{"key": "value"}\')\n'
            "print(result['key'])\n"
            "quoted = myrm_tools.shell_quote('hello world')\n"
            "print(quoted)"
        )
        context = ExecutionContext(code=script, timeout=30)
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        assert result.success
        assert "value" in (result.stdout or "")

    @pytest.mark.asyncio
    async def test_server_start_failure_is_fail_closed(self):
        """When PTC server fails to start, orchestration must not fall back to plain exec."""
        from unittest.mock import AsyncMock, patch

        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        context = ExecutionContext(code="print('fallback works')", timeout=30)
        executor = InProcessExecutor()

        with patch(
            "myrm_agent_harness.toolkits.code_execution.ptc.rpc_server.PtcRpcServer.start",
            new_callable=AsyncMock,
            side_effect=OSError("Address already in use"),
        ):
            result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        assert result.success is False
        assert result.error is not None
        assert "PTC RPC server failed to start" in result.error

    @pytest.mark.asyncio
    async def test_nested_ptc_injection_is_blocked(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.context import (
            ptc_nesting_guard,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        context = ExecutionContext(code="print('nested')", timeout=30)
        executor = InProcessExecutor()
        token = ptc_nesting_guard.set(True)
        try:
            result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        finally:
            ptc_nesting_guard.reset(token)

        assert result.success is False
        assert result.error is not None
        assert "Nested PTC execution is not allowed" in result.error

    @pytest.mark.asyncio
    async def test_existing_pythonpath_preserved(self):
        """Existing PYTHONPATH in context.env is preserved and appended."""
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            inject_ptc_for_python_execution,
        )
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        script = (
            "import os\n"
            "pp = os.environ.get('PYTHONPATH', '')\n"
            "print('HAS_CUSTOM' if '/custom/path' in pp else 'MISSING')"
        )
        context = ExecutionContext(code=script, timeout=30, env={"PYTHONPATH": "/custom/path"})
        executor = InProcessExecutor()
        result = await inject_ptc_for_python_execution(context, executor, [mock_file_read])
        assert result.success
        assert "HAS_CUSTOM" in (result.stdout or "")


class TestPtcOutputBudget:
    """PtcConfig.max_output_chars must actually clamp PTC script output."""

    def test_apply_output_budget_truncates_both_streams(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            _apply_output_budget,
        )

        result = ExecutionResult(stdout="A" * 5000, stderr="B" * 5000)
        clamped = _apply_output_budget(result, 1000)

        assert len(clamped.stdout) < len(result.stdout)
        assert len(clamped.stderr) < len(result.stderr)
        assert "[Truncated" in clamped.stdout
        assert "[Truncated" in clamped.stderr

    def test_apply_output_budget_is_noop_below_limit(self):
        from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult
        from myrm_agent_harness.toolkits.code_execution.ptc.ptc_injection import (
            _apply_output_budget,
        )

        result = ExecutionResult(stdout="short", stderr="")
        assert _apply_output_budget(result, 1000) is result

    @pytest.mark.asyncio
    async def test_injected_script_output_respects_budget(self):
        """End-to-end: the config value reaches the returned ExecutionResult."""
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            ExecutionContext,
        )
        from myrm_agent_harness.toolkits.code_execution.ptc import ptc_injection
        from tests.toolkits.code_execution._executor_stub import InProcessExecutor

        script = "print('X' * 2000)"
        context = ExecutionContext(code=script, timeout=30)
        executor = InProcessExecutor()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "myrm_agent_harness.toolkits.code_execution.ptc.models.PtcConfig",
                lambda **kwargs: PtcConfig(max_output_chars=1024, **kwargs),
            )
            result = await ptc_injection.inject_ptc_for_python_execution(context, executor, [mock_file_read])

        assert result.success
        assert "[Truncated" in (result.stdout or "")


class TestPtcRpcTransportSecurity:
    """Track 2 transport must be authenticated like Track 1, and owner-only."""

    @pytest.mark.asyncio
    async def test_request_without_token_is_rejected(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            req = PtcRpcRequest(tool="mock_file_read", args={"path": "/x"})
            payload = req.model_dump_json().encode("utf-8")
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(struct.pack("!I", len(payload)) + payload)
            await writer.drain()
            resp_len = struct.unpack("!I", await reader.readexactly(4))[0]
            resp = json.loads(await reader.readexactly(resp_len))
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

        assert resp["error"] is not None
        assert "unauthorized" in resp["error"].lower()
        assert dispatcher.records == [], "an unauthenticated request must never reach a tool"

    @pytest.mark.asyncio
    async def test_request_with_wrong_token_is_rejected(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            req = PtcRpcRequest(tool="mock_file_read", args={"path": "/x"}, auth_token="wrong")
            payload = req.model_dump_json().encode("utf-8")
            reader, writer = await asyncio.open_unix_connection(server.socket_path)
            writer.write(struct.pack("!I", len(payload)) + payload)
            await writer.drain()
            resp_len = struct.unpack("!I", await reader.readexactly(4))[0]
            resp = json.loads(await reader.readexactly(resp_len))
            writer.close()
            await writer.wait_closed()
        finally:
            await server.stop()

        assert "unauthorized" in resp["error"].lower()
        assert dispatcher.records == []

    @pytest.mark.asyncio
    async def test_socket_dir_and_file_are_owner_only(self):
        import stat as stat_mod

        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            from pathlib import Path as _Path

            sock_mode = stat_mod.S_IMODE(_Path(server.socket_path).stat().st_mode)
            dir_mode = stat_mod.S_IMODE(_Path(server.socket_path).parent.stat().st_mode)
            assert sock_mode == 0o600
            assert dir_mode == 0o700
        finally:
            await server.stop()

    @pytest.mark.asyncio
    async def test_child_env_carries_the_token(self):
        dispatcher = PtcDispatcher([mock_file_read])
        server = PtcRpcServer(PtcConfig(timeout_seconds=10), dispatcher)
        await server.start()
        try:
            assert server.get_child_env()["_MYRM_PTC_TOKEN"] == server.auth_token
        finally:
            await server.stop()
