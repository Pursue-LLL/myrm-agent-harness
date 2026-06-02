"""Unit tests for CronScheduler trigger dispatch methods.

Verifies that dispatch_event, dispatch_system_event, and dispatch_webhook
correctly delegate to TriggerProvider and fire execution.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.cron.engine.scheduler import CronScheduler
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    DeliveryConfig,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
)


def _make_job(**overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": "job-1",
        "user_id": "user-1",
        "name": "Test Job",
        "job_type": JobType.AGENT,
        "schedule": Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        "status": JobStatus.ACTIVE,
        "prompt": "test prompt",
        "delivery": DeliveryConfig(channel="chat"),
    }
    defaults.update(overrides)
    return CronJob(**defaults)  # type: ignore[arg-type]


def _make_scheduler(
    trigger_provider: AsyncMock | None = None,
) -> CronScheduler:
    store = AsyncMock()
    store.list_jobs = AsyncMock(return_value=[])
    store.earliest_next_run = AsyncMock(return_value=None)
    store.save_run = AsyncMock()
    store.save_job = AsyncMock(side_effect=lambda j: j)
    store.get_latest_integrity_hash = AsyncMock(return_value=None)

    runner = AsyncMock()
    runner.run = AsyncMock()

    delivery = AsyncMock()

    return CronScheduler(
        store=store,
        runners={JobType.AGENT: runner},
        delivery=delivery,
        config=CronConfig(),
        trigger_provider=trigger_provider,
    )


class TestDispatchWithoutProvider:
    """When no TriggerProvider is injected, dispatch methods return 0/None."""

    @pytest.mark.asyncio
    async def test_dispatch_event_returns_zero(self) -> None:
        sched = _make_scheduler(trigger_provider=None)
        result = await sched.dispatch_event("hello", "telegram", "u1")
        assert result == 0

    @pytest.mark.asyncio
    async def test_dispatch_system_event_returns_zero(self) -> None:
        sched = _make_scheduler(trigger_provider=None)
        result = await sched.dispatch_system_event("github", "push", {})
        assert result == 0

    @pytest.mark.asyncio
    async def test_dispatch_webhook_returns_none(self) -> None:
        sched = _make_scheduler(trigger_provider=None)
        result = await sched.dispatch_webhook("path", "secret", {})
        assert result is None


class TestDispatchEvent:
    @pytest.mark.asyncio
    async def test_matches_returned(self) -> None:
        job = _make_job()
        provider = AsyncMock()
        provider.check_event_triggers = AsyncMock(return_value=[job])

        sched = _make_scheduler(trigger_provider=provider)

        with patch.object(sched, "_execute_and_persist", new_callable=AsyncMock) as mock_exec:
            count = await sched.dispatch_event("error detected", "slack", "u1")
            await asyncio.sleep(0.05)

        assert count == 1
        provider.check_event_triggers.assert_awaited_once_with("error detected", "slack", "u1")
        mock_exec.assert_awaited_once()
        call_kwargs = mock_exec.call_args
        assert call_kwargs[1]["trigger_source"] == "event"
        assert "error detected" in call_kwargs[1]["context"]

    @pytest.mark.asyncio
    async def test_no_matches(self) -> None:
        provider = AsyncMock()
        provider.check_event_triggers = AsyncMock(return_value=[])

        sched = _make_scheduler(trigger_provider=provider)
        count = await sched.dispatch_event("nothing", "", "u1")

        assert count == 0

    @pytest.mark.asyncio
    async def test_provider_exception_returns_zero(self) -> None:
        provider = AsyncMock()
        provider.check_event_triggers = AsyncMock(side_effect=RuntimeError("DB down"))

        sched = _make_scheduler(trigger_provider=provider)
        count = await sched.dispatch_event("test", "", "u1")

        assert count == 0


class TestDispatchSystemEvent:
    @pytest.mark.asyncio
    async def test_matches_returned(self) -> None:
        job = _make_job()
        provider = AsyncMock()
        provider.check_system_event = AsyncMock(return_value=[job])

        sched = _make_scheduler(trigger_provider=provider)

        with patch.object(sched, "_execute_and_persist", new_callable=AsyncMock) as mock_exec:
            count = await sched.dispatch_system_event("github", "push", {"ref": "refs/heads/main"})
            await asyncio.sleep(0.05)

        assert count == 1
        provider.check_system_event.assert_awaited_once_with("github", "push", {"ref": "refs/heads/main"})
        mock_exec.assert_awaited_once()
        assert mock_exec.call_args[1]["trigger_source"] == "system_event"

    @pytest.mark.asyncio
    async def test_provider_exception_returns_zero(self) -> None:
        provider = AsyncMock()
        provider.check_system_event = AsyncMock(side_effect=RuntimeError("fail"))

        sched = _make_scheduler(trigger_provider=provider)
        count = await sched.dispatch_system_event("sentry", "alert", {})

        assert count == 0


class TestDispatchWebhook:
    @pytest.mark.asyncio
    async def test_match_returned(self) -> None:
        job = _make_job()
        provider = AsyncMock()
        provider.handle_webhook = AsyncMock(return_value=job)

        sched = _make_scheduler(trigger_provider=provider)

        with patch.object(sched, "_execute_and_persist", new_callable=AsyncMock) as mock_exec:
            result = await sched.dispatch_webhook("abc123", "secret", {"event": "test"})
            await asyncio.sleep(0.05)

        assert result is not None
        assert result.id == "job-1"
        provider.handle_webhook.assert_awaited_once_with("abc123", "secret", {"event": "test"})
        mock_exec.assert_awaited_once()
        assert mock_exec.call_args[1]["trigger_source"] == "webhook"

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self) -> None:
        provider = AsyncMock()
        provider.handle_webhook = AsyncMock(return_value=None)

        sched = _make_scheduler(trigger_provider=provider)
        result = await sched.dispatch_webhook("unknown", "", {})

        assert result is None

    @pytest.mark.asyncio
    async def test_provider_exception_returns_none(self) -> None:
        provider = AsyncMock()
        provider.handle_webhook = AsyncMock(side_effect=RuntimeError("fail"))

        sched = _make_scheduler(trigger_provider=provider)
        result = await sched.dispatch_webhook("abc", "s", {})

        assert result is None
