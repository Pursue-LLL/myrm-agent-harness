"""Tests for system resource exhaustion diagnostics and process tree causal inspection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.observability.diagnostics.process_tree import (
    ProcessNode,
    detect_orphan_processes,
    diagnose_process_tree_health,
    inspect_process_lineage,
)
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


class TestProcessTreeInspector:
    def test_inspect_process_lineage_builds_ppid_chain(self) -> None:
        proc1 = MagicMock()
        proc1.pid = 100
        proc1.ppid.return_value = 50
        proc1.name.return_value = "child_worker"
        proc1.status.return_value = "running"
        proc1.create_time.return_value = 1000.0
        proc1.memory_info.return_value = type("M", (), {"rss": 50 * 1024 * 1024})()
        proc1.cpu_percent.return_value = 5.0
        proc1.num_fds.return_value = 12

        proc2 = MagicMock()
        proc2.pid = 50
        proc2.ppid.return_value = 1
        proc2.name.return_value = "parent_runner"
        proc2.status.return_value = "sleeping"
        proc2.create_time.return_value = 900.0
        proc2.memory_info.return_value = type("M", (), {"rss": 100 * 1024 * 1024})()
        proc2.cpu_percent.return_value = 1.0
        proc2.num_fds.return_value = 20

        proc3 = MagicMock()
        proc3.pid = 1
        proc3.ppid.return_value = 0
        proc3.name.return_value = "systemd"
        proc3.status.return_value = "sleeping"
        proc3.create_time.return_value = 10.0
        proc3.memory_info.return_value = type("M", (), {"rss": 10 * 1024 * 1024})()
        proc3.cpu_percent.return_value = 0.0
        proc3.num_fds.return_value = 5

        def mock_process_factory(pid: int) -> MagicMock:
            if pid == 100:
                return proc1
            if pid == 50:
                return proc2
            if pid == 1:
                return proc3
            raise ValueError(f"Unknown pid {pid}")

        with patch("myrm_agent_harness.observability.diagnostics.process_tree.psutil") as mock_psutil:
            mock_psutil.Process.side_effect = mock_process_factory
            lineage = inspect_process_lineage(100)

        assert len(lineage) == 3
        assert [node["pid"] for node in lineage] == [100, 50, 1]
        assert lineage[0]["name"] == "child_worker"
        assert lineage[1]["name"] == "parent_runner"
        assert lineage[2]["name"] == "systemd"

    def test_detect_orphan_processes_identifies_leaked_workers(self) -> None:
        orphan_proc = MagicMock()
        orphan_proc.info = {
            "pid": 2048,
            "ppid": 1,
            "name": "camoufox-bin",
            "cmdline": ["camoufox-bin", "--headless"],
        }
        orphan_proc.pid = 2048
        orphan_proc.ppid.return_value = 1
        orphan_proc.name.return_value = "camoufox-bin"
        orphan_proc.status.return_value = "running"
        orphan_proc.create_time.return_value = 100.0
        orphan_proc.memory_info.return_value = type("M", (), {"rss": 256 * 1024 * 1024})()
        orphan_proc.cpu_percent.return_value = 12.0
        orphan_proc.num_fds.return_value = 45

        non_orphan_proc = MagicMock()
        non_orphan_proc.info = {
            "pid": 4096,
            "ppid": 100,  # normal child
            "name": "firefox",
            "cmdline": ["firefox"],
        }

        with (
            patch("myrm_agent_harness.observability.diagnostics.process_tree.psutil") as mock_psutil,
            patch("time.time", return_value=1000.0),
        ):
            mock_psutil.process_iter.return_value = [orphan_proc, non_orphan_proc]
            mock_psutil.Process.return_value = orphan_proc
            # Patch _get_process_node or let it execute
            orphans = detect_orphan_processes(min_elapsed_seconds=120.0)

        assert len(orphans) == 1
        assert orphans[0]["pid"] == 2048
        assert orphans[0]["name"] == "camoufox-bin"
        assert orphans[0]["memory_rss_mb"] == 256.0

    def test_diagnose_process_tree_health_clean_state(self) -> None:
        with (
            patch("myrm_agent_harness.observability.diagnostics.process_tree.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.process_tree.detect_orphan_processes",
                return_value=[],
            ),
        ):
            mock_psutil.pids.return_value = [1, 2, 3]
            diag = diagnose_process_tree_health()

        assert diag["orphan_count"] == 0
        assert diag["leaked_memory_mb"] == 0.0
        assert "Zero leaked worker orphans" in diag["cause_summary"]

    def test_diagnose_process_tree_health_with_orphans(self) -> None:
        dummy_orphan: ProcessNode = {
            "pid": 7777,
            "ppid": 1,
            "name": "chromium",
            "status": "sleeping",
            "elapsed_seconds": 600.0,
            "memory_rss_mb": 512.5,
            "cpu_percent": 0.5,
            "num_fds": 30,
        }
        with (
            patch("myrm_agent_harness.observability.diagnostics.process_tree.psutil") as mock_psutil,
            patch(
                "myrm_agent_harness.observability.diagnostics.process_tree.detect_orphan_processes",
                return_value=[dummy_orphan],
            ),
        ):
            mock_psutil.pids.return_value = [1, 7777]
            diag = diagnose_process_tree_health()

        assert diag["orphan_count"] == 1
        assert diag["leaked_memory_mb"] == 512.5
        assert "chromium(PID 7777, 512.5MB)" in diag["cause_summary"]
