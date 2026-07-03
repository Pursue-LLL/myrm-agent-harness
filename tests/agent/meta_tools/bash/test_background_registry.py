"""Unit tests for the background-process registry used by P1-4."""

from __future__ import annotations

import asyncio
import signal
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
    BackgroundProcessInfo,
    BackgroundProcessRegistry,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)


class _FakeStream:
    """Minimal asyncio-style ``readline`` stream returning queued lines."""

    def __init__(self, lines: list[bytes]) -> None:
        self._lines = list(lines)

    async def readline(self) -> bytes:
        if not self._lines:
            return b""
        return self._lines.pop(0)


class _FakeProc:
    """Stand-in for ``AsyncProcessProtocol`` that lets us drive lifecycle.

    The registry kills via :func:`os_compat.kill_process_group` (so it can
    propagate to forked children), not via the proc handle directly. Tests
    that want to verify kill semantics patch ``kill_process_group`` and use
    :meth:`finish` (or :meth:`stay_alive`) to drive the wait future.
    """

    def __init__(self, pid: int, stdout: list[bytes], stderr: list[bytes]) -> None:
        self._proc = MagicMock()
        self._proc.pid = pid
        self.stdout = _FakeStream(stdout)
        self.stderr = _FakeStream(stderr)
        self._exit_event = asyncio.Event()
        self._exit_code = 0

    async def wait(self) -> int:
        await self._exit_event.wait()
        return self._exit_code

    def terminate(self) -> None:  # pragma: no cover - retained for protocol compliance
        self._exit_code = -15
        self._exit_event.set()

    def kill(self) -> None:  # pragma: no cover - retained for protocol compliance
        self._exit_code = -9
        self._exit_event.set()

    def finish(self, exit_code: int = 0) -> None:
        self._exit_code = exit_code
        self._exit_event.set()


@pytest.mark.asyncio
async def test_register_captures_output_and_status_transitions() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=11111, stdout=[b"line-1\n", b"line-2\n"], stderr=[b"warn\n"])

    info = await registry.register(cast(AsyncProcessProtocol, proc), command="echo hi", session_id="s-1")

    assert isinstance(info, BackgroundProcessInfo)
    assert info.pid == 11111
    assert info.status == "running"

    listed_other = registry.list_processes(session_id="other")
    assert listed_other == []

    listed = registry.list_processes(session_id="s-1")
    assert len(listed) == 1
    assert listed[0].pid == 11111

    proc.finish(0)
    # Allow reader task to drain pipes and finalize status before snapshot.
    await asyncio.sleep(0.05)

    final = registry.get(11111)
    assert final is not None
    assert final.status == "exited"
    assert final.exit_code == 0

    output = registry.get_output(11111, max_lines=10)
    stdout_lines = cast(list[str], output["stdout"])
    stderr_lines = cast(list[str], output["stderr"])
    assert "line-1" in stdout_lines
    assert "line-2" in stdout_lines
    assert "warn" in stderr_lines
    assert isinstance(output["next_cursor"], int) and output["next_cursor"] >= 3
    assert output["dropped"] is False

    # Polling with the previous cursor should produce no new lines.
    next_cursor = output["next_cursor"]
    assert isinstance(next_cursor, int)
    follow = registry.get_output(
        11111,
        max_lines=10,
        since_cursor=next_cursor,
    )
    assert follow["stdout"] == []
    assert follow["stderr"] == []
    assert follow["next_cursor"] == output["next_cursor"]


@pytest.mark.asyncio
async def test_kill_terminates_and_marks_status() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=22222, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 60", session_id="s-2")

    sent: list[tuple[int, int]] = []

    def _record(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        proc.finish(-sig)

    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry.kill_process_group",
        side_effect=_record,
    ):
        ok = await registry.kill(22222, force=False)
    assert ok is True
    assert sent == [(22222, signal.SIGTERM)]

    await asyncio.sleep(0.02)
    snap = registry.get(22222)
    assert snap is not None
    assert snap.status == "killed"


@pytest.mark.asyncio
async def test_kill_unknown_pid_returns_false() -> None:
    registry = BackgroundProcessRegistry()
    ok = await registry.kill(99999)
    assert ok is False


@pytest.mark.asyncio
async def test_per_session_quota_blocks_new_jobs() -> None:
    registry = BackgroundProcessRegistry(per_session_limit=2)
    procs = [_FakeProc(pid=30000 + i, stdout=[], stderr=[]) for i in range(2)]
    for proc in procs:
        await registry.register(cast(AsyncProcessProtocol, proc), command="sleep 10", session_id="quota-s")

    third = _FakeProc(pid=30002, stdout=[], stderr=[])
    from myrm_agent_harness.agent.meta_tools.bash._background_registry import (
        BackgroundQuotaError,
    )

    with pytest.raises(BackgroundQuotaError):
        await registry.register(
            cast(AsyncProcessProtocol, third),
            command="sleep 10",
            session_id="quota-s",
        )

    # Releasing one slot must allow the next register.
    procs[0].finish(0)
    await asyncio.sleep(0.02)
    await registry.register(cast(AsyncProcessProtocol, third), command="sleep 10", session_id="quota-s")


@pytest.mark.asyncio
async def test_progress_listener_fires_for_explicit_marker() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(
        pid=44444,
        stdout=[b'MYRM_PROGRESS {"percent": 42, "message": "Compiling"}\n'],
        stderr=[],
    )

    events: list[dict[str, object]] = []

    async def _listener(_info: BackgroundProcessInfo, payload: dict[str, object]) -> None:
        events.append(payload)

    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="build",
        session_id="prog-s",
        progress_listener=_listener,
    )
    proc.finish(0)
    await asyncio.sleep(0.05)

    assert len(events) == 1
    assert events[0]["progress"] == 42
    assert events[0]["message"] == "Compiling"


@pytest.mark.asyncio
async def test_since_cursor_respects_cross_stream_interleave() -> None:
    """The per-line cursor must filter both streams without bleeding counts.

    Regression for the bug where a shared monotonic counter combined with
    per-stream ``[-delta:]`` slicing returned stale lines (stderr ate into
    stdout's quota).
    """
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(
        pid=66666,
        stdout=[b"out-1\n", b"out-2\n", b"out-3\n"],
        stderr=[b"err-1\n", b"err-2\n"],
    )
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="echo",
        session_id="cur-s",
    )
    await asyncio.sleep(0.02)
    first = registry.get_output(66666, max_lines=10)
    assert {"out-1", "out-2", "out-3"}.issubset(set(cast(list[str], first["stdout"])))
    assert {"err-1", "err-2"}.issubset(set(cast(list[str], first["stderr"])))

    follow = registry.get_output(
        66666, max_lines=10, since_cursor=cast(int, first["next_cursor"])
    )
    assert follow["stdout"] == []
    assert follow["stderr"] == []
    assert follow["dropped"] is False

    proc.finish(0)
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_finish_listener_invoked_on_exit() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=55555, stdout=[], stderr=[])

    seen: list[BackgroundProcessInfo] = []

    async def _on_finish(info: BackgroundProcessInfo) -> None:
        seen.append(info)

    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="sleep 1",
        session_id="fin-s",
        finish_listener=_on_finish,
    )
    proc.finish(0)
    await asyncio.sleep(0.05)

    assert len(seen) == 1
    assert seen[0].pid == 55555
    assert seen[0].status == "exited"


@pytest.mark.asyncio
async def test_kill_escalates_to_sigkill_when_sigterm_ignored() -> None:
    """O5: an unruly child that ignores SIGTERM is force-killed after grace."""
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=70000, stdout=[], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="dev-server",
        session_id="esc-s",
    )

    sent: list[tuple[int, int]] = []

    def _record(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        # SIGTERM is recorded but the process keeps running (no finish).
        # Only SIGKILL actually drops it, matching real-world unruly processes.
        if sig == signal.SIGKILL:
            proc.finish(-9)

    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry.kill_process_group",
        side_effect=_record,
    ):
        ok = await registry.kill(70000, force=False, grace_seconds=0.1)

    assert ok is True
    assert sent == [(70000, signal.SIGTERM), (70000, signal.SIGKILL)]

    await asyncio.sleep(0.02)
    snap = registry.get(70000)
    assert snap is not None
    assert snap.status == "killed"


@pytest.mark.asyncio
async def test_reap_drops_exited_entries_after_window() -> None:
    """O11: exited entries are reaped from the registry after the reap delay."""
    registry = BackgroundProcessRegistry(reap_delay_seconds=0.05)
    proc = _FakeProc(pid=80000, stdout=[b"hi\n"], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="echo hi",
        session_id="reap-s",
    )
    proc.finish(0)
    await asyncio.sleep(0.02)
    assert registry.get(80000) is not None
    await asyncio.sleep(0.1)
    assert registry.get(80000) is None
    assert registry.list_processes(session_id="reap-s") == []


@pytest.mark.asyncio
async def test_long_line_is_truncated_in_buffer() -> None:
    """O7: lines longer than ``_LINE_MAX_BYTES`` are clipped with a marker."""
    huge = b"x" * (40 * 1024) + b"\n"  # 40 KiB > 32 KiB hard cap
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=90000, stdout=[huge], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="dump",
        session_id="trunc-s",
    )
    proc.finish(0)
    await asyncio.sleep(0.02)

    out = registry.get_output(90000, max_lines=5)
    stdout_lines = cast(list[str], out["stdout"])
    assert len(stdout_lines) == 1
    assert "truncated" in stdout_lines[0]
    assert len(stdout_lines[0]) < 40 * 1024


@pytest.mark.asyncio
async def test_last_progress_captured_for_list_processes() -> None:
    """L: list_processes returns the most recent progress payload + updated_at.

    LLM polling multiple background jobs can read percent/message in a single
    list call without paying for per-pid output fetches. ``updated_at`` lets
    the model detect stale snapshots (job stopped emitting minutes ago).
    """
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(
        pid=12121,
        stdout=[
            b'MYRM_PROGRESS {"percent": 25, "message": "Compiling"}\n',
            b'MYRM_PROGRESS {"percent": 80, "message": "Linking"}\n',
        ],
        stderr=[],
    )
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="cargo build",
        session_id="L-s",
    )
    # Drive both progress markers through the reader task.
    await asyncio.sleep(0.05)

    listed = registry.list_processes(session_id="L-s")
    assert len(listed) == 1
    progress = listed[0].last_progress
    assert progress is not None
    # The newest payload must win — registry must not return the first 25% one.
    assert progress["progress"] == 80
    assert progress["message"] == "Linking"
    assert isinstance(progress["updated_at"], float)

    # to_dict() exposes the same fields for LLM JSON serialisation.
    payload = listed[0].to_dict()
    assert "last_progress" in payload
    assert cast(dict[str, object], payload["last_progress"])["progress"] == 80

    # Defensive copy: mutating the returned payload must not bleed back.
    cast(dict[str, object], listed[0].last_progress)["progress"] = 999
    fresh = registry.list_processes(session_id="L-s")[0]
    assert cast(dict[str, object], fresh.last_progress)["progress"] == 80

    proc.finish(0)
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_list_processes_omits_last_progress_when_unseen() -> None:
    """``to_dict`` must not include ``last_progress`` for jobs without progress."""
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=13131, stdout=[b"plain output\n"], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, proc),
        command="echo plain",
        session_id="np-s",
    )
    await asyncio.sleep(0.02)
    payload = registry.list_processes(session_id="np-s")[0].to_dict()
    assert "last_progress" not in payload
    proc.finish(0)
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_kill_session_jobs_only_targets_owner_session() -> None:
    """O: kill_session_jobs must signal exactly the owner session's jobs."""
    registry = BackgroundProcessRegistry()
    proc_a1 = _FakeProc(pid=14001, stdout=[], stderr=[])
    proc_a2 = _FakeProc(pid=14002, stdout=[], stderr=[])
    proc_b = _FakeProc(pid=14003, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc_a1), command="sleep 60", session_id="chat-A")
    await registry.register(cast(AsyncProcessProtocol, proc_a2), command="sleep 60", session_id="chat-A")
    await registry.register(cast(AsyncProcessProtocol, proc_b), command="sleep 60", session_id="chat-B")

    sent: list[tuple[int, int]] = []

    def _record(pid: int, sig: int) -> None:
        sent.append((pid, sig))
        if pid == 14001:
            proc_a1.finish(-sig)
        elif pid == 14002:
            proc_a2.finish(-sig)
        elif pid == 14003:
            proc_b.finish(-sig)

    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry.kill_process_group",
        side_effect=_record,
    ):
        killed = await registry.kill_session_jobs("chat-A", grace_seconds=0.05)

    assert killed == 2
    # Only chat-A pids must have been signalled. ``sent`` may also contain
    # SIGKILL escalations for pids that ignore SIGTERM in real life, but our
    # _record finishes the proc on SIGTERM so SIGKILL never fires.
    signalled_pids = {pid for pid, _ in sent}
    assert signalled_pids == {14001, 14002}

    snap_b = registry.get(14003)
    assert snap_b is not None
    assert snap_b.status == "running"
    proc_b.finish(0)
    await asyncio.sleep(0.02)


@pytest.mark.asyncio
async def test_kill_session_jobs_returns_zero_when_no_match() -> None:
    """O: kill_session_jobs is a no-op for sessions with no running jobs."""
    registry = BackgroundProcessRegistry()
    killed = await registry.kill_session_jobs("nobody-here")
    assert killed == 0


@pytest.mark.asyncio
async def test_kill_session_jobs_runs_concurrently() -> None:
    """O: 5 stubborn jobs × 0.2s grace must finish in <1.5s (not 5×0.2=1.0s sequentially).

    Concurrency guard against future refactors that loop ``await self.kill``
    serially — that would scale ``cancel`` latency with bg job count.
    """
    registry = BackgroundProcessRegistry()
    pids = list(range(15001, 15006))
    procs = [_FakeProc(pid=p, stdout=[], stderr=[]) for p in pids]
    for proc in procs:
        await registry.register(
            cast(AsyncProcessProtocol, proc),
            command="dev-server",
            session_id="concurrent-s",
        )

    pid_to_proc = dict(zip(pids, procs, strict=False))

    def _record(pid: int, sig: int) -> None:
        # SIGTERM is recorded but ignored — these jobs are "stubborn"; the
        # registry must escalate to SIGKILL after the grace window. If
        # kill_session_jobs awaited each kill() serially the total wall time
        # would be ≥ 5 × grace; concurrent dispatch keeps it near 1 × grace.
        if sig == signal.SIGKILL:
            pid_to_proc[pid].finish(-9)

    loop = asyncio.get_running_loop()
    start = loop.time()
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry.kill_process_group",
        side_effect=_record,
    ):
        killed = await registry.kill_session_jobs("concurrent-s", grace_seconds=0.2)
    elapsed = loop.time() - start

    assert killed == 5
    # Concurrent: ≈ 1 × grace (0.2s) + escalation buffer; serial would be ≥5×grace = 1.0s.
    # Allow generous headroom for CI noise.
    assert elapsed < 0.8, f"kill_session_jobs ran serially? elapsed={elapsed:.2f}s"


@pytest.mark.asyncio
async def test_shutdown_uses_process_group_kill_for_living_children() -> None:
    """``atexit`` path must route through process-group kill, not leader-only.

    Mirrors the live ``kill`` contract (PR2.6 O12): leader-only ``proc.kill()``
    would orphan ``node``/``esbuild`` grandchildren under ``npm start`` when the
    Python harness exits — process-group SIGKILL severs the whole tree.
    """
    registry = BackgroundProcessRegistry()
    proc_running = _FakeProc(pid=16001, stdout=[], stderr=[])
    proc_exited = _FakeProc(pid=16002, stdout=[], stderr=[])
    await registry.register(
        cast(AsyncProcessProtocol, proc_running), command="npm start", session_id="s1"
    )
    await registry.register(
        cast(AsyncProcessProtocol, proc_exited), command="echo done", session_id="s1"
    )
    proc_exited.finish(0)
    # Let the consumer loop transition proc_exited → exited before shutdown runs.
    await asyncio.sleep(0.05)

    killed_pids: list[tuple[int, int]] = []

    def _record(pid: int, sig: int) -> None:
        killed_pids.append((pid, sig))

    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._background_registry.kill_process_group",
        side_effect=_record,
    ):
        registry.shutdown()

    assert killed_pids == [(16001, signal.SIGKILL)], (
        f"shutdown must SIGKILL only the still-running pid via group kill; "
        f"got {killed_pids}"
    )


@pytest.mark.asyncio
async def test_list_processes_without_session_returns_all() -> None:
    """Unfiltered list must include every registered session."""
    registry = BackgroundProcessRegistry()
    proc_a = _FakeProc(pid=17001, stdout=[], stderr=[])
    proc_b = _FakeProc(pid=17002, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc_a), command="a", session_id="sess-a")
    await registry.register(cast(AsyncProcessProtocol, proc_b), command="b", session_id="sess-b")

    listed = registry.list_processes()
    pids = {row.pid for row in listed}
    assert pids == {17001, 17002}


def test_get_output_unknown_pid_returns_empty_snapshot() -> None:
    registry = BackgroundProcessRegistry()
    out = registry.get_output(99999, since_cursor=5)
    assert out == {
        "stdout": [],
        "stderr": [],
        "next_cursor": 5,
        "dropped": False,
    }


@pytest.mark.asyncio
async def test_kill_non_running_pid_is_noop_success() -> None:
    registry = BackgroundProcessRegistry()
    proc = _FakeProc(pid=18001, stdout=[], stderr=[])
    await registry.register(cast(AsyncProcessProtocol, proc), command="echo done", session_id="done-s")
    proc.finish(0)
    await asyncio.sleep(0.05)

    ok = await registry.kill(18001)
    assert ok is True


def test_get_background_registry_returns_singleton() -> None:
    from myrm_agent_harness.agent.meta_tools.bash import _background_registry as mod

    mod._registry = None
    first = mod.get_background_registry()
    second = mod.get_background_registry()
    assert first is second
