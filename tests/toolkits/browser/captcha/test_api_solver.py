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
    async def test_inject_hcaptcha_token(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()

        result = await solver._inject_token(page, "hcap-token", CaptchaType.HCAPTCHA)

        assert result is True
        page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_inject_cloudflare_turnstile_token(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()

        result = await solver._inject_token(page, "cf-token", CaptchaType.CLOUDFLARE_TURNSTILE)

        assert result is True
        page.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_inject_cloudflare_challenge_token(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()

        result = await solver._inject_token(page, "cf-token", CaptchaType.CLOUDFLARE_CHALLENGE)

        assert result is True

    @pytest.mark.asyncio
    async def test_inject_unsupported_type_returns_false(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()

        result = await solver._inject_token(page, "token", CaptchaType.UNKNOWN)

        assert result is False

    @pytest.mark.asyncio
    async def test_inject_exception_returns_false(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()
        page.evaluate = AsyncMock(side_effect=RuntimeError("evaluate failed"))

        result = await solver._inject_token(page, "token", CaptchaType.RECAPTCHA)

        assert result is False


class TestApiSolverPollResult:
    """Tests for CapSolver getTaskResult polling."""

    @pytest.mark.asyncio
    async def test_poll_result_ready(self) -> None:
        solver = ApiSolver(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "ready",
            "solution": {"gRecaptchaResponse": "solved-token-xyz"},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            token = await solver._poll_result("task-123")

        assert token == "solved-token-xyz"

    @pytest.mark.asyncio
    async def test_poll_result_failed(self) -> None:
        solver = ApiSolver(api_key="test-key")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "failed",
            "errorDescription": "Task failed",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            token = await solver._poll_result("task-123")

        assert token is None

    @pytest.mark.asyncio
    async def test_poll_result_exception_continues(self) -> None:
        solver = ApiSolver(api_key="test-key")

        ready_response = MagicMock()
        ready_response.json.return_value = {
            "status": "ready",
            "solution": {"token": "fallback-token"},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=[RuntimeError("network"), ready_response]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            token = await solver._poll_result("task-123")

        assert token == "fallback-token"


class TestApiSolverCreateTaskException:
    """Tests for createTask network failures."""

    @pytest.mark.asyncio
    async def test_create_task_network_error_returns_none(self) -> None:
        solver = ApiSolver(api_key="test-key")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            task_id = await solver._create_task(
                "ReCaptchaV2TaskProxyLess", "https://example.com", "sitekey"
            )

        assert task_id is None


class TestApiSolverFullFlow:
    """End-to-end solve flow with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_full_solve_success(self) -> None:
        solver = ApiSolver(api_key="test-key")
        html = '<div data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>'
        page = _make_mock_page(html)
        info = _make_info(CaptchaType.RECAPTCHA)

        create_resp = MagicMock()
        create_resp.json.return_value = {"errorId": 0, "taskId": "t-1"}

        poll_resp = MagicMock()
        poll_resp.json.return_value = {
            "status": "ready",
            "solution": {"gRecaptchaResponse": "solved"},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[create_resp, poll_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await solver.solve(info, page)

        assert result.success is True
        assert result.method == "capsolver"

    @pytest.mark.asyncio
    async def test_full_solve_create_task_fails(self) -> None:
        solver = ApiSolver(api_key="test-key")
        html = '<div data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>'
        page = _make_mock_page(html)
        info = _make_info(CaptchaType.RECAPTCHA)

        create_resp = MagicMock()
        create_resp.json.return_value = {"errorId": 1, "errorDescription": "bad key"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=create_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await solver.solve(info, page)

        assert result.success is False
        assert "createTask failed" in result.message

    @pytest.mark.asyncio
    async def test_full_solve_poll_returns_none(self) -> None:
        solver = ApiSolver(api_key="test-key")
        html = '<div data-sitekey="6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"></div>'
        page = _make_mock_page(html)
        info = _make_info(CaptchaType.RECAPTCHA)

        create_resp = MagicMock()
        create_resp.json.return_value = {"errorId": 0, "taskId": "t-2"}

        poll_resp = MagicMock()
        poll_resp.json.return_value = {"status": "failed", "errorDescription": "timeout"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[create_resp, poll_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await solver.solve(info, page)

        assert result.success is False
        assert "timed out or failed" in result.message


class TestApiSolverExtractSitekeyEdgeCases:
    """Edge cases for sitekey extraction."""

    @pytest.mark.asyncio
    async def test_extract_sitekey_no_pattern(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page("<html></html>")

        key = await solver._extract_sitekey(page, CaptchaType.UNKNOWN)

        assert key is None

    @pytest.mark.asyncio
    async def test_extract_sitekey_page_content_exception(self) -> None:
        solver = ApiSolver(api_key="test-key")
        page = _make_mock_page()
        page.content = AsyncMock(side_effect=RuntimeError("page closed"))

        key = await solver._extract_sitekey(page, CaptchaType.RECAPTCHA)

        assert key is None
