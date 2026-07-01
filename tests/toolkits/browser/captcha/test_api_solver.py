"""Tests for ApiSolver — CapSolver REST API implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.captcha.api_solver import ApiSolver
from myrm_agent_harness.toolkits.browser.captcha.protocols import (
    CaptchaInfo,
    CaptchaType,
)


def _make_info(captcha_type: CaptchaType = CaptchaType.RECAPTCHA) -> CaptchaInfo:
    return CaptchaInfo(captcha_type=captcha_type, reason="Test CAPTCHA")


def _make_mock_page(html: str = "") -> MagicMock:
    """Create a mock Page with content() returning the given HTML."""
    page = MagicMock()
    page.url = "https://example.com"
    page.content = AsyncMock(return_value=html)
    page.evaluate = AsyncMock(return_value=None)
    return page


class TestApiSolverUnsupportedType:
    """Tests for unsupported CAPTCHA types."""

    @pytest.mark.asyncio
    async def test_unsupported_captcha_type_returns_failure(self) -> None:
        solver = ApiSolver(api_key="test-key")
        info = _make_info(CaptchaType.UNKNOWN)
        page = _make_mock_page()

        result = await solver.solve(info, page)

        assert result.success is False
        assert result.method == "capsolver"
        assert "Unsupported" in result.message


class TestApiSolverSitekeyExtraction:
    """Tests for site key extraction from HTML."""

    @pytest.mark.asyncio
    async def test_missing_sitekey_returns_failure(self) -> None:
        solver = ApiSolver(api_key="test-key")
        info = _make_info(CaptchaType.RECAPTCHA)
        page = _make_mock_page("<html><body>No captcha here</body></html>")

        result = await solver.solve(info, page)

        assert result.success is False
        assert "website key" in result.message

    @pytest.mark.asyncio
    async def test_recaptcha_sitekey_extracted(self) -> None:
        solver = ApiSolver(api_key="test-key")
        html = '<div data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>'
        page = _make_mock_page(html)

        key = await solver._extract_sitekey(page, CaptchaType.RECAPTCHA)

        assert key == "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"

    @pytest.mark.asyncio
    async def test_hcaptcha_sitekey_extracted(self) -> None:
        solver = ApiSolver(api_key="test-key")
        html = '<div data-sitekey="10000000-ffff-ffff-ffff-000000000001"></div>'
        page = _make_mock_page(html)

        key = await solver._extract_sitekey(page, CaptchaType.HCAPTCHA)

        assert key == "10000000-ffff-ffff-ffff-000000000001"


class TestApiSolverCreateTask:
    """Tests for CapSolver createTask API call."""

    @pytest.mark.asyncio
    async def test_create_task_success(self) -> None:
        solver = ApiSolver(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"errorId": 0, "taskId": "task-123"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            task_id = await solver._create_task("ReCaptchaV2TaskProxyLess", "https://example.com", "sitekey")

        assert task_id == "task-123"

    @pytest.mark.asyncio
    async def test_create_task_error_returns_none(self) -> None:
        solver = ApiSolver(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {"errorId": 1, "errorDescription": "Invalid key"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            task_id = await solver._create_task("ReCaptchaV2TaskProxyLess", "https://example.com", "sitekey")

        assert task_id is None


class TestApiSolverInjectToken:
    """Tests for token injection."""

    @pytest.mark.asyncio
    async def test_inject_recaptcha_token(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()

        result = await solver._inject_token(page, "solved-token-abc", CaptchaType.RECAPTCHA)

        assert result is True
        page.evaluate.assert_called_once()
        call_args = page.evaluate.call_args
        assert call_args[0][1] == "solved-token-abc"

    @pytest.mark.asyncio
    async def test_inject_unsupported_type_returns_false(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()

        result = await solver._inject_token(page, "token", CaptchaType.UNKNOWN)

        assert result is False
