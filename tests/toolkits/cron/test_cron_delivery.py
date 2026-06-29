"""Unit tests for WebhookDelivery."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.cron.delivery import WebhookDelivery, _is_permanent_error
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryConfig,
    JobResult,
    JobType,
    Schedule,
    ScheduleKind,
)

_SCHEDULE = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=60_000)


def _job(url: str = "https://example.com/hook", secret: str | None = None) -> CronJob:
    from datetime import UTC, datetime

    return CronJob(
        id="j1",
        user_id="u1",
        name="test",
        job_type=JobType.SHELL,
        command="echo hi",
        schedule=_SCHEDULE,
        delivery=DeliveryConfig(channel="webhook", target=url, secret=secret),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _result(success: bool = True, output: str = "ok") -> JobResult:
    return JobResult(success=success, output=output)


class TestIsPermanentError:
    def test_value_error(self) -> None:
        assert _is_permanent_error(ValueError("bad")) is True

    def test_runtime_4xx(self) -> None:
        assert _is_permanent_error(RuntimeError("Webhook returned 400: bad")) is True

    def test_runtime_5xx(self) -> None:
        assert _is_permanent_error(RuntimeError("Webhook returned 500: err")) is False

    def test_other(self) -> None:
        assert _is_permanent_error(ConnectionError("timeout")) is False


class TestWebhookDelivery:
    @pytest.fixture
    def delivery(self) -> WebhookDelivery:
        return WebhookDelivery(max_retries=1)

    async def test_deliver_success(self, delivery: WebhookDelivery) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        with patch("myrm_agent_harness.toolkits.cron.delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_secure:
                await delivery.deliver(_job(), _result())
                mock_secure.assert_awaited_once()

    async def test_deliver_missing_url(self, delivery: WebhookDelivery) -> None:
        with pytest.raises(ValueError, match="Webhook URL missing"):
            await delivery.deliver(_job(url=""), _result())

    async def test_deliver_4xx_no_retry(self, delivery: WebhookDelivery) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"

        with patch("myrm_agent_harness.toolkits.cron.delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_secure:
                with pytest.raises(RuntimeError, match="Webhook returned 400"):
                    await delivery.deliver(_job(), _result())
                assert mock_secure.await_count == 1

    async def test_deliver_5xx_retries(self, delivery: WebhookDelivery) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Error"

        with patch("myrm_agent_harness.toolkits.cron.delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_secure:
                with patch("asyncio.sleep", new_callable=AsyncMock):
                    with pytest.raises(RuntimeError, match="Webhook returned 500"):
                        await delivery.deliver(_job(), _result())
                    assert mock_secure.await_count == 2

    async def test_hmac_signature_present(self, delivery: WebhookDelivery) -> None:
        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        with patch("myrm_agent_harness.toolkits.cron.delivery.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            with patch(
                "myrm_agent_harness.core.security.http.secure_fetch.secure_request",
                new_callable=AsyncMock,
                return_value=mock_resp,
            ) as mock_secure:
                await delivery.deliver(_job(secret="mysecret"), _result())
                call_kwargs = mock_secure.call_args.kwargs
                headers = call_kwargs["headers"]
                assert "X-Webhook-Signature" in headers
                assert headers["X-Webhook-Signature"].startswith("sha256=")
