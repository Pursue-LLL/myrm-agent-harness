"""Tests for system resource exhaustion diagnostics."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from myrm_agent_harness.observability.diagnostics.system_exhaustion import (
    check_system_exhaustion,
    get_system_exhaustion_snapshot,
)


class TestSystemExhaustionProbe:
    @pytest.mark.asyncio
    async def test_check_system_exhaustion_pass_when_healthy(self) -> None:
        mock_swap = type(
            "SwapMem",
            (),
            {"total": 8 * 1024 * 1024 * 1024, "used": 1 * 1024 * 1024 * 1024, "percent": 12.5},
        )()
        with (
            patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_linux_commit_info",
                return_value=(1000, 2000),
            ),
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_system_fd_usage",
                return_value=(500, 10000, 5.0),
            ),
        ):
            mock_psutil.swap_memory.return_value = mock_swap
            report = await check_system_exhaustion()

        assert report.status == "pass"
        assert "healthy" in report.message
        assert report.component_name == "SystemExhaustion"

    @pytest.mark.asyncio
    async def test_check_system_exhaustion_warn_when_swap_elevated(self) -> None:
        mock_swap = type(
            "SwapMem",
            (),
            {"total": 8 * 1024 * 1024 * 1024, "used": 6 * 1024 * 1024 * 1024, "percent": 75.0},
        )()
        with (
            patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_linux_commit_info",
                return_value=(1000, 2000),
            ),
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_system_fd_usage",
                return_value=(500, 10000, 5.0),
            ),
        ):
            mock_psutil.swap_memory.return_value = mock_swap
            report = await check_system_exhaustion()

        assert report.status == "warn"
        assert "Swap/Pagefile usage is high" in report.message

    @pytest.mark.asyncio
    async def test_check_system_exhaustion_fail_when_swap_saturated(self) -> None:
        mock_swap = type(
            "SwapMem",
            (),
            {"total": 8 * 1024 * 1024 * 1024, "used": 7800 * 1024 * 1024, "percent": 95.0},
        )()
        with (
            patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_linux_commit_info",
                return_value=(1000, 2000),
            ),
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_system_fd_usage",
                return_value=(500, 10000, 5.0),
            ),
        ):
            mock_psutil.swap_memory.return_value = mock_swap
            report = await check_system_exhaustion()

        assert report.status == "fail"
        assert "critically saturated" in report.message
        assert report.cause is not None

    @pytest.mark.asyncio
    async def test_check_system_exhaustion_fail_when_fd_exhausted(self) -> None:
        mock_swap = type(
            "SwapMem",
            (),
            {"total": 8 * 1024 * 1024 * 1024, "used": 1 * 1024 * 1024 * 1024, "percent": 12.5},
        )()
        with (
            patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_linux_commit_info",
                return_value=(1000, 2000),
            ),
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_system_fd_usage",
                return_value=(9500, 10000, 95.0),
            ),
        ):
            mock_psutil.swap_memory.return_value = mock_swap
            report = await check_system_exhaustion()

        assert report.status == "fail"
        assert "EMFILE" in report.message

    @pytest.mark.asyncio
    async def test_check_system_exhaustion_fail_when_commit_limit_exceeded(self) -> None:
        mock_swap = type(
            "SwapMem",
            (),
            {"total": 8 * 1024 * 1024 * 1024, "used": 1 * 1024 * 1024 * 1024, "percent": 12.5},
        )()
        with (
            patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_linux_commit_info",
                return_value=(5000, 4000),
            ),
            patch(
                "myrm_agent_harness.observability.diagnostics.system_exhaustion._read_system_fd_usage",
                return_value=(100, 10000, 1.0),
            ),
        ):
            mock_psutil.swap_memory.return_value = mock_swap
            report = await check_system_exhaustion()

        assert report.status == "fail"
        assert "commit limit is exceeded" in report.message

    @pytest.mark.asyncio
    async def test_check_system_exhaustion_warn_when_psutil_missing(self) -> None:
        with patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.psutil", None):
            report = await check_system_exhaustion()
        assert report.status == "warn"
        assert "psutil library is missing" in (report.detail or "")

    def test_get_system_exhaustion_snapshot_fields(self) -> None:
        snapshot = get_system_exhaustion_snapshot()
        assert "platform" in snapshot
        assert "swap_percent" in snapshot
        assert "commit_exhausted" in snapshot
        assert "fd_allocated" in snapshot

    def test_read_linux_commit_info_parsing(self, tmp_path) -> None:
        from myrm_agent_harness.observability.diagnostics.system_exhaustion import _read_linux_commit_info
        fake_meminfo = tmp_path / "meminfo"
        fake_meminfo.write_text(
            "MemTotal:        16384000 kB\n"
            "CommitLimit:      8192000 kB\n"
            "Committed_AS:     9000000 kB\n",
            encoding="utf-8",
        )
        with patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.Path") as mock_path:
            mock_path.return_value = fake_meminfo
            committed, limit = _read_linux_commit_info()
        assert committed == 9000000
        assert limit == 8192000

    def test_read_linux_commit_info_missing_file(self) -> None:
        from myrm_agent_harness.observability.diagnostics.system_exhaustion import _read_linux_commit_info
        with patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.Path") as mock_path:
            mock_path.return_value.exists.return_value = False
            committed, limit = _read_linux_commit_info()
        assert committed is None
        assert limit is None

    def test_read_system_fd_usage_linux_proc(self, tmp_path) -> None:
        from myrm_agent_harness.observability.diagnostics.system_exhaustion import _read_system_fd_usage
        fake_file_nr = tmp_path / "file-nr"
        fake_file_nr.write_text("1024\t0\t1048576\n", encoding="utf-8")
        with (
            patch("sys.platform", "linux"),
            patch("myrm_agent_harness.observability.diagnostics.system_exhaustion.Path") as mock_path,
        ):
            mock_path.return_value = fake_file_nr
            alloc, max_fd, ratio = _read_system_fd_usage()
        assert alloc == 1024
        assert max_fd == 1048576
        assert ratio is not None
        assert round(ratio, 4) == round((1024 / 1048576) * 100, 4)
