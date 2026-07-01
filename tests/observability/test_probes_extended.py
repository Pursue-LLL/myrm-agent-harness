"""Extended tests for observability diagnostics probes.

Covers probes NOT tested in test_probes.py:
- check_network_health: httpx present/absent, success/failure
- check_qdrant_health: vector store available/import error/connection error
- check_system_resources: psutil present/absent, various thresholds
- check_tokenizer_health: jieba/bigram/broken/import error
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCheckNetworkHealth:
    @pytest.mark.asyncio
    async def test_httpx_missing_returns_warn(self):
        with patch.dict("sys.modules", {"httpx": None}):
            with patch(
                "myrm_agent_harness.observability.diagnostics.probes.httpx",
                None,
            ):
                from importlib import reload

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
        import myrm_agent_harness.observability.diagnostics.probes as probes_mod

        original_psutil = probes_mod.psutil
        probes_mod.psutil = None
        try:
            report = await probes_mod.check_system_resources()
            assert report.status == "warn"
            assert "psutil" in report.detail.lower()
        finally:
            probes_mod.psutil = original_psutil

    @pytest.mark.asyncio
    async def test_healthy_resources(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_system_resources

        mock_memory = MagicMock()
        mock_memory.percent = 50.0
        mock_memory.used = 8 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with patch("psutil.cpu_percent", return_value=30.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ):
            report = await check_system_resources()
            assert report.status == "pass"
            assert "healthy" in report.message.lower()

    @pytest.mark.asyncio
    async def test_high_memory_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_system_resources

        mock_memory = MagicMock()
        mock_memory.percent = 85.0
        mock_memory.used = 13 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with patch("psutil.cpu_percent", return_value=30.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ):
            report = await check_system_resources()
            assert report.status == "warn"
            assert report.measured is not None
            assert "85" in report.measured

    @pytest.mark.asyncio
    async def test_critical_memory_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_system_resources

        mock_memory = MagicMock()
        mock_memory.percent = 96.0
        mock_memory.used = 15 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with patch("psutil.cpu_percent", return_value=30.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ):
            report = await check_system_resources()
            assert report.status == "fail"
            assert "critically" in report.message.lower()

    @pytest.mark.asyncio
    async def test_high_cpu_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_system_resources

        mock_memory = MagicMock()
        mock_memory.percent = 50.0
        mock_memory.used = 8 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with patch("psutil.cpu_percent", return_value=85.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ):
            report = await check_system_resources()
            assert report.status == "warn"
            assert "cpu" in report.measured.lower()

    @pytest.mark.asyncio
    async def test_critical_cpu_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_system_resources

        mock_memory = MagicMock()
        mock_memory.percent = 50.0
        mock_memory.used = 8 * (1024**3)
        mock_memory.total = 16 * (1024**3)

        with patch("psutil.cpu_percent", return_value=96.0), patch(
            "psutil.virtual_memory", return_value=mock_memory
        ):
            report = await check_system_resources()
            assert report.status == "fail"
            assert "cpu" in report.message.lower()

    @pytest.mark.asyncio
    async def test_exception_returns_fail(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_system_resources

        with patch("psutil.cpu_percent", side_effect=RuntimeError("access denied")):
            report = await check_system_resources()
            assert report.status == "fail"
            assert "access denied" in report.detail.lower()


class TestCheckQdrantHealth:
    @pytest.mark.asyncio
    async def test_vector_toolkit_missing_returns_warn(self):
        from myrm_agent_harness.observability.diagnostics.probes import check_qdrant_health

        with patch(
            "myrm_agent_harness.observability.diagnostics.probes.check_qdrant_health",
            wraps=check_qdrant_health,
        ):
            with patch.dict("sys.modules", {"myrm_agent_harness.toolkits.vector": None}):
                with patch(
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
