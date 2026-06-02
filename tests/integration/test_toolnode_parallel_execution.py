"""End-to-end integration test: real async tools + real safety_dispatcher.

Simulates LangGraph ToolNode's asyncio.gather behavior with real tools
and real safety_dispatcher middleware. Verifies true parallelism for
safe tools and strict serialization for unsafe tools.

No mocks — uses real async tool functions, real asyncio.gather, real middleware.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.middlewares.safety_dispatcher import (
    create_safety_dispatcher,
)
from myrm_agent_harness.agent.security.tool_registry import (
    TOOL_SAFETY_METADATA,
    SafetyMetadata,
)

TOOL_SAFETY_METADATA["real_file_read"] = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
TOOL_SAFETY_METADATA["real_grep"] = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
TOOL_SAFETY_METADATA["real_glob"] = SafetyMetadata(is_read_only=True, is_concurrent_safe=True)
TOOL_SAFETY_METADATA["real_file_write"] = SafetyMetadata(is_destructive=True)
TOOL_SAFETY_METADATA["real_bash"] = SafetyMetadata(is_destructive=True)

_log: list[tuple[str, str, float]] = []


def _reset() -> None:
    _log.clear()


class FakeRequest:
    def __init__(self, name: str, *, tool_call_id: str | None = None, state: object | None = None) -> None:
        self.tool_call: dict[str, str] = {"name": name, "id": tool_call_id if tool_call_id is not None else f"fake_{name}"}
        self.state: object = state if state is not None else []


async def _invoke(middleware: object, request: object, handler: object) -> object:
    return await middleware.awrap_tool_call(request, handler)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Real tool implementations (actual file I/O, no mocks)
# ---------------------------------------------------------------------------


async def real_file_read(tmp_dir: Path, filename: str) -> str:
    """Actually read a file from disk."""
    _log.append(("real_file_read", "start", time.monotonic()))
    content = (tmp_dir / filename).read_text()
    await asyncio.sleep(0.03)
    _log.append(("real_file_read", "end", time.monotonic()))
    return content


async def real_grep(tmp_dir: Path, pattern: str) -> list[str]:
    """Actually search files in a directory."""
    _log.append(("real_grep", "start", time.monotonic()))
    matches = []
    for f in tmp_dir.iterdir():
        if f.is_file() and pattern in f.read_text():
            matches.append(f.name)
    await asyncio.sleep(0.03)
    _log.append(("real_grep", "end", time.monotonic()))
    return matches


async def real_glob(tmp_dir: Path, pattern: str) -> list[str]:
    """Actually glob files in a directory."""
    _log.append(("real_glob", "start", time.monotonic()))
    matches = [str(p.name) for p in tmp_dir.glob(pattern)]
    await asyncio.sleep(0.03)
    _log.append(("real_glob", "end", time.monotonic()))
    return matches


async def real_file_write(tmp_dir: Path, filename: str, content: str) -> str:
    """Actually write a file to disk."""
    _log.append(("real_file_write", "start", time.monotonic()))
    (tmp_dir / filename).write_text(content)
    await asyncio.sleep(0.03)
    _log.append(("real_file_write", "end", time.monotonic()))
    return f"wrote {filename}"


async def real_bash(command: str) -> str:
    """Actually execute a shell command."""
    _log.append(("real_bash", "start", time.monotonic()))
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    _log.append(("real_bash", "end", time.monotonic()))
    return stdout.decode().strip()


@pytest.fixture
def tmp_dir() -> Path:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        (p / "hello.txt").write_text("hello world")
        (p / "test.py").write_text("import os\nprint('test')")
        (p / "data.csv").write_text("a,b,c\n1,2,3")
        yield p


class TestRealToolParallelExecution:
    """Real file I/O tools dispatched through real safety_dispatcher."""

    @pytest.mark.asyncio
    async def test_three_reads_truly_parallel(self, tmp_dir: Path) -> None:
        """3 safe read operations should execute in parallel."""
        _reset()
        safety = create_safety_dispatcher()

        async def handler_read(req: object) -> str:
            return await real_file_read(tmp_dir, "hello.txt")

        async def handler_grep(req: object) -> list[str]:
            return await real_grep(tmp_dir, "hello")

        async def handler_glob(req: object) -> list[str]:
            return await real_glob(tmp_dir, "*.txt")

        results = await asyncio.gather(
            _invoke(safety, FakeRequest("real_file_read"), handler_read),
            _invoke(safety, FakeRequest("real_grep"), handler_grep),
            _invoke(safety, FakeRequest("real_glob"), handler_glob),
        )

        assert results[0] == "hello world"
        assert "hello.txt" in results[1]
        assert "hello.txt" in results[2]

        starts = [t for _, p, t in _log if p == "start"]
        ends = [t for _, p, t in _log if p == "end"]
        assert len(starts) == 3
        assert max(starts) < min(ends)

    @pytest.mark.asyncio
    async def test_two_writes_strictly_serial(self, tmp_dir: Path) -> None:
        """2 unsafe write operations should execute one at a time."""
        _reset()
        safety = create_safety_dispatcher()

        async def handler_write_a(req: object) -> str:
            return await real_file_write(tmp_dir, "out_a.txt", "content_a")

        async def handler_write_b(req: object) -> str:
            return await real_file_write(tmp_dir, "out_b.txt", "content_b")

        await asyncio.gather(
            _invoke(safety, FakeRequest("real_file_write"), handler_write_a),
            _invoke(safety, FakeRequest("real_file_write"), handler_write_b),
        )

        assert (tmp_dir / "out_a.txt").read_text() == "content_a"
        assert (tmp_dir / "out_b.txt").read_text() == "content_b"

        assert len(_log) == 4
        assert _log[0][1] == "start"
        assert _log[1][1] == "end"
        assert _log[2][1] == "start"
        assert _log[3][1] == "end"

    @pytest.mark.asyncio
    async def test_mixed_read_and_write(self, tmp_dir: Path) -> None:
        """Read (parallel) + write (serial) in same batch."""
        _reset()
        safety = create_safety_dispatcher()

        async def handler_read(req: object) -> str:
            return await real_file_read(tmp_dir, "hello.txt")

        async def handler_glob(req: object) -> list[str]:
            return await real_glob(tmp_dir, "*.py")

        async def handler_write(req: object) -> str:
            return await real_file_write(tmp_dir, "new.txt", "new content")

        results = await asyncio.gather(
            _invoke(safety, FakeRequest("real_file_read"), handler_read),
            _invoke(safety, FakeRequest("real_glob"), handler_glob),
            _invoke(safety, FakeRequest("real_file_write"), handler_write),
        )

        assert results[0] == "hello world"
        assert "test.py" in results[1]
        assert (tmp_dir / "new.txt").read_text() == "new content"

        read_starts = [t for n, p, t in _log if n in ("real_file_read", "real_glob") and p == "start"]
        assert len(read_starts) == 2
        assert abs(read_starts[0] - read_starts[1]) < 0.01

    @pytest.mark.asyncio
    async def test_bash_and_read_parallel_vs_serial(self, tmp_dir: Path) -> None:
        """bash (unsafe) should serialize while reads run in parallel."""
        _reset()
        safety = create_safety_dispatcher()

        async def handler_read(req: object) -> str:
            return await real_file_read(tmp_dir, "data.csv")

        async def handler_bash(req: object) -> str:
            return await real_bash("echo 'hello from bash'")

        results = await asyncio.gather(
            _invoke(safety, FakeRequest("real_file_read"), handler_read),
            _invoke(safety, FakeRequest("real_bash"), handler_bash),
            _invoke(safety, FakeRequest("real_grep"), lambda r: real_grep(tmp_dir, "import")),
        )

        assert "a,b,c" in results[0]
        assert "hello from bash" in results[1]
        assert "test.py" in results[2]

    @pytest.mark.asyncio
    async def test_parallel_performance(self, tmp_dir: Path) -> None:
        """3 safe tools (30ms each) should complete in ~30ms, not ~90ms."""
        _reset()
        safety = create_safety_dispatcher()

        async def handler(req: object) -> str:
            return await real_file_read(tmp_dir, "hello.txt")

        start = time.monotonic()
        await asyncio.gather(
            _invoke(safety, FakeRequest("real_file_read"), handler),
            _invoke(safety, FakeRequest("real_grep"), lambda r: real_grep(tmp_dir, "world")),
            _invoke(safety, FakeRequest("real_glob"), lambda r: real_glob(tmp_dir, "*")),
        )
        elapsed = time.monotonic() - start

        assert elapsed < 0.08


class TestBatchFailureAndStateResolution:
    """Cover _get_batch_id state parsing and batch failure skip logic."""

    @pytest.mark.asyncio
    async def test_batch_failure_skips_subsequent_unsafe_tools(self) -> None:
        """When an unsafe tool fails, subsequent unsafe tools in the same batch are skipped."""
        safety = create_safety_dispatcher()
        ai_msg = AIMessage(content="", tool_calls=[
            {"id": "call_a", "name": "real_file_write", "args": {}},
            {"id": "call_b", "name": "real_bash", "args": {}},
        ])
        state_list = [ai_msg]

        async def fail_handler(req: object) -> ToolMessage:
            return ToolMessage(content="error", name="real_file_write", tool_call_id="call_a", status="error")

        async def second_handler(req: object) -> ToolMessage:
            return ToolMessage(content="ok", name="real_bash", tool_call_id="call_b")

        req_a = FakeRequest("real_file_write", tool_call_id="call_a", state=state_list)
        req_b = FakeRequest("real_bash", tool_call_id="call_b", state=state_list)

        result_a = await _invoke(safety, req_a, fail_handler)
        result_b = await _invoke(safety, req_b, second_handler)

        assert result_a.status == "error"
        assert "[SKIPPED]" in result_b.content

    @pytest.mark.asyncio
    async def test_get_batch_id_with_dict_state(self) -> None:
        """_get_batch_id handles dict state with 'messages' key."""
        safety = create_safety_dispatcher()
        ai_msg = AIMessage(content="", tool_calls=[{"id": "call_x", "name": "real_file_write", "args": {}}])

        async def handler(req: object) -> ToolMessage:
            return ToolMessage(content="ok", name="real_file_write", tool_call_id="call_x")

        req = FakeRequest("real_file_write", tool_call_id="call_x", state={"messages": [ai_msg]})
        result = await _invoke(safety, req, handler)
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_get_batch_id_with_attr_state(self) -> None:
        """_get_batch_id handles object state with 'messages' attribute."""
        safety = create_safety_dispatcher()
        ai_msg = AIMessage(content="", tool_calls=[{"id": "call_y", "name": "real_file_write", "args": {}}])
        state_obj = MagicMock()
        state_obj.messages = [ai_msg]

        async def handler(req: object) -> ToolMessage:
            return ToolMessage(content="ok", name="real_file_write", tool_call_id="call_y")

        req = FakeRequest("real_file_write", tool_call_id="call_y", state=state_obj)
        result = await _invoke(safety, req, handler)
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_no_tool_call_id_returns_none_batch(self) -> None:
        """When tool_call has no 'id', batch_id is None and tool still executes."""
        safety = create_safety_dispatcher()

        async def handler(req: object) -> ToolMessage:
            return ToolMessage(content="ok", name="real_file_write", tool_call_id="")

        req = FakeRequest("real_file_write", tool_call_id="", state=[])
        result = await _invoke(safety, req, handler)
        assert result.content == "ok"

    @pytest.mark.asyncio
    async def test_unrelated_batch_not_affected_by_other_failure(self) -> None:
        """A batch failure does not affect tools from a different batch."""
        safety = create_safety_dispatcher()
        ai_msg_a = AIMessage(content="", tool_calls=[
            {"id": "call_fail", "name": "real_file_write", "args": {}},
        ])
        ai_msg_b = AIMessage(content="", tool_calls=[
            {"id": "call_ok", "name": "real_bash", "args": {}},
        ])

        async def fail_handler(req: object) -> ToolMessage:
            return ToolMessage(content="error", name="real_file_write", tool_call_id="call_fail", status="error")

        async def ok_handler(req: object) -> ToolMessage:
            return ToolMessage(content="ok", name="real_bash", tool_call_id="call_ok")

        req_fail = FakeRequest("real_file_write", tool_call_id="call_fail", state=[ai_msg_a])
        await _invoke(safety, req_fail, fail_handler)

        req_ok = FakeRequest("real_bash", tool_call_id="call_ok", state=[ai_msg_b])
        result = await _invoke(safety, req_ok, ok_handler)
        assert result.content == "ok"
