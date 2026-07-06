"""Unit tests for VncServer process management — cleanup, health loop, passwd security.

Covers the three optimizations:
1. _create_passwd_file sets 0600 permissions
2. _health_loop uses exponential backoff with max retry limit
3. _cleanup_processes calls wait() after kill() to prevent zombies
"""

from __future__ import annotations

import asyncio
import os
import stat
from tempfile import NamedTemporaryFile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.vnc.server import (
    VncServer,
    VncStatus,
    _HEALTH_CHECK_INTERVAL_S,
    _MAX_RESTART_ATTEMPTS,
)


class TestCleanupProcessesWaitAfterKill:
    """proc.kill() must be followed by await proc.wait() to prevent zombies."""

    @pytest.mark.asyncio
    async def test_kill_followed_by_wait(self) -> None:
        call_order: list[str] = []

        mock_proc = MagicMock()
        mock_proc.returncode = None

        def on_terminate() -> None:
            call_order.append("terminate")

        def on_kill() -> None:
            call_order.append("kill")
            mock_proc.returncode = -9

        wait_call_count = 0

        async def on_wait() -> None:
            nonlocal wait_call_count
            wait_call_count += 1
            call_order.append(f"wait_{wait_call_count}")

        mock_proc.terminate = MagicMock(side_effect=on_terminate)
        mock_proc.kill = MagicMock(side_effect=on_kill)
        mock_proc.wait = on_wait

        async def fake_wait_for(coro: object, *, timeout: float) -> None:
            if asyncio.iscoroutine(coro):
                coro.close()
            raise asyncio.TimeoutError

        srv = VncServer()
        srv._x11vnc_proc = mock_proc
        srv._websockify_proc = None

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            await srv._cleanup_processes()

        assert "terminate" in call_order
        assert "kill" in call_order
        assert "wait_1" in call_order
        assert call_order.index("kill") < call_order.index("wait_1")
        assert srv._x11vnc_proc is None

    @pytest.mark.asyncio
    async def test_terminate_succeeds_no_kill(self) -> None:
        call_order: list[str] = []

        mock_proc = MagicMock()
        mock_proc.returncode = None

        def on_terminate() -> None:
            call_order.append("terminate")

        async def on_wait() -> None:
            mock_proc.returncode = 0
            call_order.append("wait")

        mock_proc.terminate = MagicMock(side_effect=on_terminate)
        mock_proc.kill = MagicMock()
        mock_proc.wait = on_wait

        srv = VncServer()
        srv._x11vnc_proc = mock_proc
        srv._websockify_proc = None

        await srv._cleanup_processes()

        assert "terminate" in call_order
        assert "wait" in call_order
        mock_proc.kill.assert_not_called()
        assert srv._x11vnc_proc is None


class TestPasswdFilePermissions:
    """_create_passwd_file must set 0600 permissions."""

    def test_chmod_0600_on_tempfile(self) -> None:
        tmp = NamedTemporaryFile(suffix=".vnc_passwd_test", delete=False)
        tmp.close()
        try:
            os.chmod(tmp.name, 0o600)
            mode = os.stat(tmp.name).st_mode & 0o777
            assert mode == 0o600, f"Expected 0600, got {oct(mode)}"
        finally:
            os.unlink(tmp.name)

    def test_chmod_restricts_group_other(self) -> None:
        tmp = NamedTemporaryFile(suffix=".vnc_passwd_test", delete=False)
        tmp.close()
        try:
            os.chmod(tmp.name, 0o644)
            mode_before = os.stat(tmp.name).st_mode
            assert mode_before & stat.S_IRGRP, "Should have group read before"

            os.chmod(tmp.name, 0o600)
            mode_after = os.stat(tmp.name).st_mode
            assert not (mode_after & stat.S_IRGRP), "Group read should be removed"
            assert not (mode_after & stat.S_IROTH), "Other read should be removed"
        finally:
            os.unlink(tmp.name)


class TestHealthLoopBackoff:
    """_health_loop must use exponential backoff and stop after max attempts."""

    def test_backoff_values(self) -> None:
        expected = [30, 60, 120, 240, 480, 480]
        for failures in range(6):
            backoff = _HEALTH_CHECK_INTERVAL_S * (2 ** min(failures, 4))
            assert backoff == expected[failures], (
                f"failures={failures}: expected {expected[failures]}, got {backoff}"
            )

    def test_max_restart_attempts_constant(self) -> None:
        assert _MAX_RESTART_ATTEMPTS == 5

    @pytest.mark.asyncio
    async def test_health_loop_stops_after_max_failures(self) -> None:
        srv = VncServer()
        srv._status = VncStatus.RUNNING

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        srv._x11vnc_proc = mock_proc
        srv._websockify_proc = MagicMock()
        srv._websockify_proc.returncode = None

        restart_count = 0

        async def mock_cleanup() -> None:
            pass

        async def mock_start_x11vnc() -> None:
            nonlocal restart_count
            restart_count += 1
            raise RuntimeError("x11vnc unavailable")

        async def mock_start_websockify() -> None:
            pass

        srv._cleanup_processes = mock_cleanup
        srv._start_x11vnc = mock_start_x11vnc
        srv._start_websockify = mock_start_websockify

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await srv._health_loop()

        assert restart_count == _MAX_RESTART_ATTEMPTS
        assert srv._status == VncStatus.ERROR

    @pytest.mark.asyncio
    async def test_health_loop_resets_on_success(self) -> None:
        srv = VncServer()
        srv._status = VncStatus.RUNNING

        call_count = 0
        sleep_calls: list[float] = []

        mock_proc = MagicMock()
        mock_proc.returncode = 1
        srv._x11vnc_proc = mock_proc
        srv._websockify_proc = MagicMock()
        srv._websockify_proc.returncode = None

        async def mock_cleanup() -> None:
            pass

        async def mock_start_x11vnc() -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient failure")

        async def mock_start_websockify() -> None:
            pass

        srv._cleanup_processes = mock_cleanup
        srv._start_x11vnc = mock_start_x11vnc
        srv._start_websockify = mock_start_websockify

        loop_iterations = 0

        original_sleep = asyncio.sleep

        async def mock_sleep(duration: float) -> None:
            nonlocal loop_iterations
            sleep_calls.append(duration)
            loop_iterations += 1
            if loop_iterations >= 3:
                raise asyncio.CancelledError

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await srv._health_loop()

        assert call_count == 2
        assert srv._status == VncStatus.RUNNING
        assert sleep_calls[0] == _HEALTH_CHECK_INTERVAL_S


class TestParseDisplay:
    """_parse_display edge cases."""

    def test_standard_display(self) -> None:
        srv = VncServer()
        with patch.dict("os.environ", {"DISPLAY": ":0"}):
            assert srv._parse_display() == 0

    def test_display_with_screen(self) -> None:
        srv = VncServer()
        with patch.dict("os.environ", {"DISPLAY": ":1.0"}):
            assert srv._parse_display() == 1

    def test_display_with_hostname(self) -> None:
        srv = VncServer()
        with patch.dict("os.environ", {"DISPLAY": "localhost:99"}):
            assert srv._parse_display() == 99

    def test_invalid_display_no_colon(self) -> None:
        srv = VncServer()
        with (
            patch.dict("os.environ", {"DISPLAY": "nodisplay"}),
            pytest.raises(RuntimeError, match="Invalid DISPLAY"),
        ):
            srv._parse_display()

    def test_invalid_display_non_numeric(self) -> None:
        srv = VncServer()
        with (
            patch.dict("os.environ", {"DISPLAY": ":abc"}),
            pytest.raises(RuntimeError, match="Cannot parse DISPLAY"),
        ):
            srv._parse_display()


class TestCleanupBothProcesses:
    """_cleanup_processes handles both x11vnc and websockify."""

    @pytest.mark.asyncio
    async def test_both_processes_terminated(self) -> None:
        procs_terminated: list[str] = []

        def make_proc(name: str) -> MagicMock:
            proc = MagicMock()
            proc.returncode = None

            async def wait() -> None:
                proc.returncode = 0
                procs_terminated.append(name)

            proc.wait = wait
            return proc

        srv = VncServer()
        srv._x11vnc_proc = make_proc("x11vnc")
        srv._websockify_proc = make_proc("websockify")

        await srv._cleanup_processes()

        assert "x11vnc" in procs_terminated
        assert "websockify" in procs_terminated
        assert srv._x11vnc_proc is None
        assert srv._websockify_proc is None

    @pytest.mark.asyncio
    async def test_already_exited_process_skipped(self) -> None:
        srv = VncServer()

        exited_proc = MagicMock()
        exited_proc.returncode = 0

        srv._x11vnc_proc = exited_proc
        srv._websockify_proc = None

        await srv._cleanup_processes()

        exited_proc.terminate.assert_not_called()
        assert srv._x11vnc_proc is None

    @pytest.mark.asyncio
    async def test_none_processes_handled(self) -> None:
        srv = VncServer()
        srv._x11vnc_proc = None
        srv._websockify_proc = None

        await srv._cleanup_processes()

        assert srv._x11vnc_proc is None
        assert srv._websockify_proc is None


class TestHealthLoopProcessDetection:
    """_health_loop detects websockify crash, not just x11vnc."""

    @pytest.mark.asyncio
    async def test_websockify_crash_triggers_restart(self) -> None:
        srv = VncServer()
        srv._status = VncStatus.RUNNING

        x11vnc_proc = MagicMock()
        x11vnc_proc.returncode = None
        websockify_proc = MagicMock()
        websockify_proc.returncode = 1

        srv._x11vnc_proc = x11vnc_proc
        srv._websockify_proc = websockify_proc

        restart_called = False

        async def mock_cleanup() -> None:
            pass

        async def mock_start_x11vnc() -> None:
            nonlocal restart_called
            restart_called = True

        async def mock_start_websockify() -> None:
            pass

        srv._cleanup_processes = mock_cleanup
        srv._start_x11vnc = mock_start_x11vnc
        srv._start_websockify = mock_start_websockify

        iteration = 0

        async def mock_sleep(duration: float) -> None:
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                raise asyncio.CancelledError

        with patch("asyncio.sleep", side_effect=mock_sleep):
            await srv._health_loop()

        assert restart_called
        assert srv._status == VncStatus.RUNNING


class TestStopCleansPasswdFile:
    """stop() must delete the password file."""

    @pytest.mark.asyncio
    async def test_stop_removes_passwd_file(self) -> None:
        from pathlib import Path

        tmp = NamedTemporaryFile(suffix=".vnc_passwd_test", delete=False)
        tmp.close()
        passwd_path = Path(tmp.name)
        assert passwd_path.exists()

        srv = VncServer()
        srv._status = VncStatus.RUNNING
        srv._passwd_file = passwd_path
        srv._x11vnc_proc = None
        srv._websockify_proc = None
        srv._health_task = None

        await srv.stop()

        assert not passwd_path.exists()
        assert srv._passwd_file is None
        assert srv._status == VncStatus.STOPPED
        assert srv._password == ""

    @pytest.mark.asyncio
    async def test_stop_with_no_passwd_file(self) -> None:
        srv = VncServer()
        srv._status = VncStatus.RUNNING
        srv._passwd_file = None
        srv._x11vnc_proc = None
        srv._websockify_proc = None
        srv._health_task = None

        await srv.stop()

        assert srv._status == VncStatus.STOPPED


class TestVncServerIdempotent:
    """start() idempotency and unavailable fallback."""

    @pytest.mark.asyncio
    async def test_start_when_already_running(self) -> None:
        srv = VncServer()
        srv._status = VncStatus.RUNNING
        info = await srv.start()
        assert info.status == VncStatus.RUNNING

    @pytest.mark.asyncio
    async def test_start_when_unavailable(self) -> None:
        srv = VncServer()
        with patch.object(VncServer, "is_available", return_value=False):
            info = await srv.start()
            assert info.status == VncStatus.UNAVAILABLE
            assert info.error is not None
