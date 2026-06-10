# Before importing, we must mock sys.platform to properly test branches.
# However, os_compat uses IS_WIN at module level.
# We will reload the module with patching.
import importlib
import signal
import sys
from unittest.mock import MagicMock, patch

import pytest

import myrm_agent_harness.utils.os_compat as os_compat


@pytest.fixture
def win32_env():
    mock_msvcrt = MagicMock()
    mock_msvcrt.LK_NBLCK = 1
    mock_msvcrt.LK_LOCK = 2
    mock_msvcrt.LK_UNLCK = 3
    with patch.dict("sys.modules", {"msvcrt": mock_msvcrt}), patch("sys.platform", "win32"):
        importlib.reload(os_compat)
        yield
    importlib.reload(os_compat)


@pytest.fixture
def posix_env():
    with patch("sys.platform", "linux"):
        importlib.reload(os_compat)
        yield
    importlib.reload(os_compat)


def test_get_process_group_kwargs_win32(win32_env):
    kwargs = os_compat.get_process_group_kwargs()
    assert "creationflags" in kwargs


def test_get_process_group_kwargs_posix(posix_env):
    kwargs = os_compat.get_process_group_kwargs()
    assert "start_new_session" in kwargs
    assert kwargs["start_new_session"] is True


def test_kill_process_group_win32(win32_env):
    with patch("subprocess.run") as mock_run:
        os_compat.kill_process_group(12345)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "taskkill" in args
        assert str(12345) in args


def test_kill_process_group_posix(posix_env):
    def mock_getpgid(p):
        if p == 12345:
            return 54321
        return 11111

    with patch("os.getpgid", side_effect=mock_getpgid), patch(
        "os.getpid", return_value=11111
    ), patch("os.killpg") as mock_killpg:
        os_compat.kill_process_group(12345)
        mock_killpg.assert_called_once_with(54321, signal.SIGKILL)

    # Test safety check (shares process group with parent)
    def mock_getpgid_same(p):
        return 11111

    with patch("os.getpgid", side_effect=mock_getpgid_same), patch(
        "os.getpid", return_value=11111
    ), patch("os.kill") as mock_kill:
        os_compat.kill_process_group(12345)
        mock_kill.assert_called_once_with(12345, signal.SIGKILL)

    # Test process lookup error
    with patch("os.getpgid", side_effect=ProcessLookupError):
        # Should silently ignore
        os_compat.kill_process_group(12345)


def test_win_lock_emulation(win32_env):
    mock_msvcrt = sys.modules["msvcrt"]

    with patch("os.lseek", return_value=0):
        os_compat.flock(1, os_compat.LOCK_EX | os_compat.LOCK_NB)
        mock_msvcrt.locking.assert_called_with(1, mock_msvcrt.LK_NBLCK, 1)

        os_compat.flock(1, os_compat.LOCK_UN)
        mock_msvcrt.locking.assert_called_with(1, mock_msvcrt.LK_UNLCK, 1)

        os_compat.lockf(1, os_compat.LOCK_EX, length=10)
        mock_msvcrt.locking.assert_called_with(1, mock_msvcrt.LK_LOCK, 10)

        mock_msvcrt.locking.side_effect = OSError("resource busy")
        with pytest.raises(BlockingIOError):
            os_compat.flock(1, os_compat.LOCK_EX | os_compat.LOCK_NB)

        mock_msvcrt.locking.side_effect = OSError("permission denied")
        with pytest.raises(OSError, match="permission denied"):
            os_compat.flock(1, os_compat.LOCK_EX)


def test_terminate_process_graceful_escalates_to_sigkill(posix_env):
    alive = {"value": True}

    def mock_getpgid(pid: int) -> int:
        if pid == 12345:
            return 54321
        return 11111

    def mock_killpg(_pgid: int, sig: int) -> None:
        if sig == signal.SIGKILL:
            alive["value"] = False

    def mock_kill(pid: int, sig: int) -> None:
        if pid == 12345 and sig == 0 and not alive["value"]:
            raise ProcessLookupError

    with (
        patch("os.getpgid", side_effect=mock_getpgid),
        patch("os.getpid", return_value=11111),
        patch("os.killpg", side_effect=mock_killpg),
        patch("os.kill", side_effect=mock_kill),
        patch("time.sleep"),
        patch("time.monotonic", side_effect=[0.0, 3.0]),
    ):
        os_compat.terminate_process_graceful(12345, grace_seconds=2.0)

    assert alive["value"] is False


def test_posix_lock(posix_env):
    if sys.platform == "win32":
        pytest.skip("Cannot reliably mock fcntl on Windows host")

    with patch("fcntl.flock") as mock_flock:
        os_compat.flock(1, os_compat.LOCK_EX)
        mock_flock.assert_called_once_with(1, os_compat.LOCK_EX)

    with patch("fcntl.lockf") as mock_lockf:
        os_compat.lockf(1, os_compat.LOCK_EX, 10)
        mock_lockf.assert_called_once_with(1, os_compat.LOCK_EX, 10, 0, 0)
