"""Extended tests for observability diagnostics probes.

Covers probes NOT tested in test_probes.py:
- check_network_health: httpx present/absent, success/failure
- check_qdrant_health: vector store available/import error/connection error
- check_system_resources: psutil present/absent, various thresholds
- check_tokenizer_health: jieba/bigram/broken/import error
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCheckNetworkHealth:
    @pytest.mark.asyncio
    async def test_httpx_missing_returns_warn(self):
        with patch.dict("sys.modules", {"httpx": None}), patch(
            "myrm_agent_harness.observability.diagnostics.probes.httpx",
            None,
        ):

            import myrm_agent_harness.observability.diagnostics.probes as probes_mod

            original_httpx = probes_mod.httpx
            probes_mod.httpx = None
            try:
                report = await probes_mod.check_network_health()
                assert report.status == "warn"
                assert "httpx" in report.detail.lower()
            finally:
                probes_mod.httpx = original_httpx

    @pytest.mark.asyncio
    async def test_successful_probe(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_network_health

        mock_response = MagicMock()
        mock_response.status_code = 204

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            report = await check_network_health()
            assert report.status == "pass"
            assert report.component_name == "Network"

    @pytest.mark.asyncio
    async def test_all_probes_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_network_health

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("no network"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            report = await check_network_health()
            assert report.status == "fail"
            assert "unreachable" in report.detail.lower()

    @pytest.mark.asyncio
    async def test_server_error_tries_next(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_network_health

        call_count = 0

        async def get_with_fallback(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                resp = MagicMock()
                resp.status_code = 500
                return resp
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client = AsyncMock()
        mock_client.get = get_with_fallback
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            report = await check_network_health()
            assert report.status == "pass"


class TestCheckSystemResources:
    @pytest.mark.asyncio
    async def test_psutil_missing_returns_warn(self):
        import myrm_agent_harness.observability.diagnostics.system_resources as probes_mod

        original_psutil = probes_mod.psutil
        probes_mod.psutil = None
        try:
            report = await probes_mod.check_system_resources()
            assert report.status == "warn"
            assert "psutil" in report.detail.lower()
        finally:
            probes_mod.psutil = original_psutil

    @staticmethod
    @contextmanager
    def _patched_resources(
        *,
        cpu: float = 30.0,
        memory_percent: float = 50.0,
        usage: tuple[int | None, int | None] = (None, None),
        tree: tuple[int, int] = (0, 0),
        top: str = "",
    ):
        """Context manager patching all resource sampling helpers deterministically."""
        mock_memory = MagicMock()
        mock_memory.percent = memory_percent
        mock_memory.used = 8 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with ExitStack() as stack:
            stack.enter_context(patch("psutil.cpu_percent", return_value=cpu))
            stack.enter_context(patch("psutil.virtual_memory", return_value=mock_memory))
            stack.enter_context(
                patch("myrm_agent_harness.observability.diagnostics.system_resources._read_pid_usage", return_value=usage)
            )
            stack.enter_context(
                patch("myrm_agent_harness.observability.diagnostics.system_resources._sample_process_tree", return_value=tree)
            )
            stack.enter_context(
                patch("myrm_agent_harness.observability.diagnostics.system_resources._top_memory_processes", return_value=top)
            )
            yield

    @pytest.mark.asyncio
    async def test_healthy_resources(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with self._patched_resources():
            report = await check_system_resources()
            assert report.status == "pass"
            assert "healthy" in report.message.lower()

    @pytest.mark.asyncio
    async def test_high_memory_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with self._patched_resources(memory_percent=85.0):
            report = await check_system_resources()
            assert report.status == "warn"
            assert report.measured is not None
            assert "85" in report.measured

    @pytest.mark.asyncio
    async def test_critical_memory_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with self._patched_resources(memory_percent=96.0):
            report = await check_system_resources()
            assert report.status == "fail"
            assert "critically" in report.message.lower()

    @pytest.mark.asyncio
    async def test_high_cpu_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with self._patched_resources(cpu=85.0):
            report = await check_system_resources()
            assert report.status == "warn"
            assert "cpu" in report.measured.lower()

    @pytest.mark.asyncio
    async def test_critical_cpu_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with self._patched_resources(cpu=96.0):
            report = await check_system_resources()
            assert report.status == "fail"
            assert "cpu" in report.message.lower()

    @pytest.mark.asyncio
    async def test_exception_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with ExitStack() as stack:
            stack.enter_context(patch("psutil.cpu_percent", side_effect=RuntimeError("access denied")))
            for ctx in (
                patch("myrm_agent_harness.observability.diagnostics.system_resources._read_pid_usage", return_value=(None, None)),
                patch(
                    "myrm_agent_harness.observability.diagnostics.system_resources._sample_process_tree", return_value=(0, 0)
                ),
                patch("myrm_agent_harness.observability.diagnostics.system_resources._top_memory_processes", return_value=""),
            ):
                stack.enter_context(ctx)
            report = await check_system_resources()
        assert report.status == "fail"
        assert "access denied" in report.detail.lower()


class TestPidSaturation:
    """PID utilization dimension of check_system_resources."""

    @staticmethod
    def _report(usage, tree=(5, 3)):
        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        mock_memory = MagicMock()
        mock_memory.percent = 50.0
        mock_memory.used = 8 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with patch("psutil.cpu_percent", return_value=30.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ), patch(
            "myrm_agent_harness.observability.diagnostics.system_resources._read_pid_usage",
            return_value=usage,
        ), patch(
            "myrm_agent_harness.observability.diagnostics.system_resources._sample_process_tree",
            return_value=tree,
        ), patch(
            "myrm_agent_harness.observability.diagnostics.system_resources._top_memory_processes",
            return_value="",
        ):
            import asyncio

            return asyncio.run(check_system_resources())

    def test_critical_pid_usage_returns_fail(self):
        report = self._report((95, 100))
        assert report.status == "fail"
        assert "process count" in report.message.lower()
        assert "95/100" in report.measured
        assert report.fix_suggestion is not None

    def test_high_pid_usage_returns_warn(self):
        report = self._report((75, 100))
        assert report.status == "warn"
        assert "75/100" in report.measured

    def test_moderate_pid_usage_keeps_pass(self):
        report = self._report((50, 100))
        assert report.status == "pass"
        assert "PID: 50/100" in report.detail

    def test_no_cgroup_degrades_to_process_count(self):
        report = self._report((None, None), tree=(12, 4))
        assert report.status == "pass"
        assert "Processes: 12 (browser 4)" in report.detail

    def test_pid_check_takes_precedence_over_memory_warn(self):
        mock_memory = MagicMock()
        mock_memory.percent = 85.0
        mock_memory.used = 13 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        from myrm_agent_harness.observability.diagnostics.system_resources import check_system_resources

        with patch("psutil.cpu_percent", return_value=30.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ), patch(
            "myrm_agent_harness.observability.diagnostics.system_resources._read_pid_usage",
            return_value=(95, 100),
        ), patch(
            "myrm_agent_harness.observability.diagnostics.system_resources._sample_process_tree",
            return_value=(30, 25),
        ):
            import asyncio

            report = asyncio.run(check_system_resources())
            assert report.status == "fail"
            assert "process" in report.message.lower()

    def test_read_cgroup_pid_file_max_returns_none(self, tmp_path):
        from myrm_agent_harness.observability.diagnostics.system_resources import _read_cgroup_pid_file

        target = tmp_path / "pids.max"
        target.write_text("max\n", encoding="utf-8")
        assert _read_cgroup_pid_file(str(target)) is None

        target.write_text("512\n", encoding="utf-8")
        assert _read_cgroup_pid_file(str(target)) == 512

        assert _read_cgroup_pid_file(str(tmp_path / "missing")) is None

    def test_read_pid_usage_falls_back_to_v1(self, tmp_path, monkeypatch):
        from myrm_agent_harness.observability.diagnostics.system_resources import _read_pid_usage

        v1_dir = tmp_path / "v1"
        (v1_dir / "pids").mkdir(parents=True)
        (v1_dir / "pids" / "pids.current").write_text("42\n", encoding="utf-8")
        (v1_dir / "pids" / "pids.max").write_text("200\n", encoding="utf-8")

        monkeypatch.setattr(
            "myrm_agent_harness.observability.diagnostics.system_resources._CGROUP_PIDS_FILES",
            ((str(v1_dir / "pids" / "pids.current"), str(v1_dir / "pids" / "pids.max")),),
        )
        assert _read_pid_usage() == (42, 200)

    def test_read_pid_usage_absent_returns_none(self, tmp_path, monkeypatch):
        from myrm_agent_harness.observability.diagnostics.system_resources import _read_pid_usage

        monkeypatch.setattr(
            "myrm_agent_harness.observability.diagnostics.system_resources._CGROUP_PIDS_FILES",
            ((str(tmp_path / "missing.current"), str(tmp_path / "missing.max")),),
        )
        assert _read_pid_usage() == (None, None)

    def test_sample_process_tree_classifies_browser_children(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import _sample_process_tree

        browser_proc = MagicMock()
        browser_proc.name.return_value = "firefox"
        browser_proc.cmdline.return_value = ["/usr/lib/firefox", "--profile", "/tmp/x"]

        server_proc = MagicMock()
        server_proc.name.return_value = "python"
        server_proc.cmdline.return_value = ["python", "-m", "myrm_agent_server"]

        root_proc = MagicMock()
        root_proc.children.return_value = [browser_proc, server_proc]

        with patch(
            "myrm_agent_harness.observability.diagnostics.system_resources.psutil.Process",
            return_value=root_proc,
        ):
            total, browser = _sample_process_tree()
        assert total == 2
        assert browser == 1

    def test_top_memory_processes_ranks_descending(self):
        from myrm_agent_harness.observability.diagnostics.system_resources import _top_memory_processes

        procs = [
            {"name": "python", "memory_percent": 5.0},
            {"name": "firefox", "memory_percent": 12.3},
            {"name": "node", "memory_percent": 2.0},
        ]

        class FakeP:
            info = None

            def __init__(self, info):
                self.info = info

        with patch(
            "myrm_agent_harness.observability.diagnostics.system_resources.psutil.process_iter",
            return_value=[FakeP(p) for p in procs],
        ):
            summary = _top_memory_processes(limit=3)
        assert "firefox 12.3%" in summary
        assert summary.index("firefox") < summary.index("python") < summary.index("node")


class TestCheckQdrantHealth:
    @pytest.mark.asyncio
    async def test_vector_toolkit_missing_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_qdrant_health

        with patch(
            "myrm_agent_harness.observability.diagnostics.probes.check_qdrant_health",
            wraps=check_qdrant_health,
        ), patch.dict("sys.modules", {"myrm_agent_harness.toolkits.vector": None}), patch(
            "builtins.__import__",
            side_effect=ImportError("No module named 'myrm_agent_harness.toolkits.vector'"),
        ):
            report = await check_qdrant_health()
            assert report.status == "warn"

    @pytest.mark.asyncio
    async def test_successful_qdrant(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_qdrant_health

        mock_config_cls = MagicMock()
        mock_create = AsyncMock()

        with patch(
            "myrm_agent_harness.toolkits.vector.VectorStoreConfig",
            mock_config_cls,
        ), patch(
            "myrm_agent_harness.toolkits.vector.qdrant.create_vector_store",
            mock_create,
        ):
            report = await check_qdrant_health()
            assert report.status == "pass"
            assert report.component_name == "VectorDB"

    @pytest.mark.asyncio
    async def test_connection_error_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_qdrant_health

        mock_config_cls = MagicMock()
        mock_create = AsyncMock(side_effect=ConnectionError("refused"))

        with patch(
            "myrm_agent_harness.toolkits.vector.VectorStoreConfig",
            mock_config_cls,
        ), patch(
            "myrm_agent_harness.toolkits.vector.qdrant.create_vector_store",
            mock_create,
        ):
            report = await check_qdrant_health()
            assert report.status == "fail"
            assert "connection" in report.detail.lower()


class TestCheckTokenizerHealth:
    @pytest.mark.asyncio
    async def test_jieba_healthy(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_tokenizer_health

        mock_service = MagicMock()
        mock_service.backend = "jieba"
        mock_service.tokenize.return_value = ["机器", "学习"]

        with patch(
            "myrm_agent_harness.toolkits.retriever.bm25.get_tokenizer_service",
            return_value=mock_service,
        ):
            report = await check_tokenizer_health()
            assert report.status == "pass"
            assert "jieba" in report.detail.lower()

    @pytest.mark.asyncio
    async def test_bigram_fallback_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_tokenizer_health

        mock_service = MagicMock()
        mock_service.backend = "bigram_fallback"
        mock_service.tokenize.return_value = ["机器", "器学", "学习"]

        with patch(
            "myrm_agent_harness.toolkits.retriever.bm25.get_tokenizer_service",
            return_value=mock_service,
        ):
            report = await check_tokenizer_health()
            assert report.status == "warn"
            assert "bigram" in report.detail.lower()
            assert "jieba" in report.fix_suggestion.lower()

    @pytest.mark.asyncio
    async def test_broken_tokenizer_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_tokenizer_health

        mock_service = MagicMock()
        mock_service.backend = "jieba"
        mock_service.tokenize.return_value = ["机器学习"]  # only 1 token = broken

        with patch(
            "myrm_agent_harness.toolkits.retriever.bm25.get_tokenizer_service",
            return_value=mock_service,
        ):
            report = await check_tokenizer_health()
            assert report.status == "fail"
            assert "cjk" in report.message.lower()

    @pytest.mark.asyncio
    async def test_import_error_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_tokenizer_health

        with patch(
            "myrm_agent_harness.toolkits.retriever.bm25.get_tokenizer_service",
            side_effect=ImportError("no module"),
        ):
            report = await check_tokenizer_health()
            assert report.status == "fail"
