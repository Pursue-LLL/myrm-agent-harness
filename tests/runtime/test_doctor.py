"""Tests for runtime/doctor.py - Global Doctor diagnostics."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.runtime.doctor import (
    Doctor,
    _get_module_version,
    run_global_doctor,
)
from myrm_agent_harness.runtime.doctor_cli import format_styled_report
from myrm_agent_harness.toolkits.browser.doctor import CheckStatus, DoctorCheckResult, DoctorReport


class TestPythonVersionCheck:
    @pytest.mark.asyncio
    async def test_current_python_passes(self):
        result = await Doctor()._check_python()
        assert result.status == CheckStatus.OK
        assert result.name == "python"
        version_str = f"{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}"
        assert version_str in result.message

    @pytest.mark.asyncio
    async def test_old_python_fails(self):
        with patch.object(sys, "version_info", (3, 12, 0, "final", 0)):
            result = await Doctor()._check_python()
            assert result.status == CheckStatus.ERROR
            assert "Update to 3.13+" in result.fix


class TestCoreDependenciesCheck:
    @pytest.mark.asyncio
    async def test_all_installed(self):
        result = await Doctor()._check_core_deps()
        assert result.status == CheckStatus.OK
        assert result.name == "core_deps"

    @pytest.mark.asyncio
    async def test_missing_dependency(self):
        with patch("myrm_agent_harness.runtime.doctor._cached_find_spec", return_value=None):
            result = await Doctor()._check_core_deps()
            assert result.status == CheckStatus.ERROR
            assert result.fix == "uv sync"


class TestOptionalDependenciesCheck:
    @pytest.mark.asyncio
    async def test_returns_list(self):
        results = await Doctor()._check_optional_deps()
        assert isinstance(results, list)
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_each_result_has_correct_name_prefix(self):
        results = await Doctor()._check_optional_deps()
        for r in results:
            assert r.name.startswith("opt_")


class TestLLMConfigCheck:
    @pytest.mark.asyncio
    async def test_both_configured(self):
        with patch.dict("os.environ", {"MYRM_MODEL_NAME": "gpt-4o", "MYRM_API_KEY": "sk-test1234567890"}):
            result = await Doctor()._check_llm_config()
            assert result.status == CheckStatus.OK
            assert "gpt-4o" in result.message

    @pytest.mark.asyncio
    async def test_both_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await Doctor()._check_llm_config()
            assert result.status == CheckStatus.ERROR


class TestRunGlobalDoctor:
    @pytest.mark.asyncio
    async def test_basic_run_no_browser(self):
        report = await run_global_doctor(include_browser=False)
        assert report.overall_healthy is not None
        assert "python" in report.checks
        assert "core_deps" in report.checks
        assert "llm_config" in report.checks

    @pytest.mark.asyncio
    async def test_no_browser_excludes_browser_checks(self):
        report = await run_global_doctor(include_browser=False)
        # In our refactored doctor, browser suite tasks are not even gathered
        # We can check if any browser specific checks are present
        browser_checks = [n for n in report.checks if n.startswith("browser_")]
        assert len(browser_checks) == 0


class TestFormatGlobalReport:
    @pytest.mark.asyncio
    async def test_format_produces_string(self):
        report = await run_global_doctor(include_browser=False)
        output = format_styled_report(report)
        assert isinstance(output, str)
        assert "Myrm Agent Harness" in output

    def test_format_deduplicates_recommendations(self):
        report = DoctorReport(
            checks={
                "a": DoctorCheckResult(name="a", status=CheckStatus.ERROR, message="fail", fix="uv sync"),
                "b": DoctorCheckResult(name="b", status=CheckStatus.ERROR, message="fail", fix="uv sync"),
            },
            summary="0/2 checks passed",
            overall_healthy=False,
            recommendations=["uv sync", "uv sync"],
        )
        # Using Doctor's internal build_report logic check or Mock
        dr = Doctor()
        final_rep = dr._build_report(report.checks)
        assert len(final_rep.recommendations) == 1
        assert final_rep.recommendations[0] == "uv sync"


class TestLLMConnectivity:
    @pytest.mark.asyncio
    async def test_missing_config_returns_error(self):
        with patch.dict("os.environ", {}, clear=True):
            result = await Doctor()._check_llm_connectivity()
            assert result.status == CheckStatus.ERROR

    @pytest.mark.asyncio
    async def test_successful_connectivity(self):
        from unittest.mock import AsyncMock

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.head = AsyncMock(return_value=mock_response)
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        mock_litellm = MagicMock()
        mock_litellm.get_llm_provider = MagicMock(return_value=(None, None, "https://api.openai.com/v1", None))

        with patch.dict("os.environ", {"MYRM_MODEL_NAME": "gpt-4o", "MYRM_API_KEY": "sk-123"}):
            with patch.dict("sys.modules", {"litellm": mock_litellm}):
                with patch("httpx.AsyncClient", return_value=mock_client_instance):
                    result = await Doctor()._check_llm_connectivity()
                    assert result.status == CheckStatus.OK


class TestGetModuleVersion:
    def test_known_module(self):
        # pytest is definitely here
        version = _get_module_version("pytest")
        assert version is not None

    def test_unknown_module(self):
        version = _get_module_version("nonexistent_module_xyz_123")
        assert version is None
