"""Unit tests for output hash deduplication in JobExecutor."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.cron.engine.executor import JobExecutor, _output_hash
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryStatus,
    JobResult,
    JobType,
    Schedule,
    ScheduleKind,
)


def _make_job(*, deduplicate: bool = False, last_output_hash: str | None = None) -> CronJob:
    return CronJob(
        id="test-job",
        user_id="user-1",
        name="Test Job",
        job_type=JobType.AGENT,
        schedule=Schedule(kind=ScheduleKind.CRON, expr="0 * * * *"),
        deduplicate=deduplicate,
        last_output_hash=last_output_hash,
    )


class TestOutputHash:
    def test_deterministic(self):
        assert _output_hash("hello") == _output_hash("hello")

    def test_different_inputs(self):
        assert _output_hash("hello") != _output_hash("world")

    def test_strips_whitespace(self):
        assert _output_hash("  hello  ") == _output_hash("hello")

    def test_returns_32_chars(self):
        result = _output_hash("test")
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)

    def test_matches_sha256_prefix(self):
        text = "test output"
        expected = hashlib.sha256(text.strip().encode()).hexdigest()[:32]
        assert _output_hash(text) == expected


class TestDeduplication:
    @pytest.fixture()
    def executor(self) -> JobExecutor:
        store = AsyncMock()
        store.save_job = AsyncMock()
        store.save_run = AsyncMock()
        delivery = AsyncMock()
        delivery.deliver = AsyncMock()
        return JobExecutor(store=store, delivery=delivery)

    @pytest.mark.asyncio
    async def test_dedup_off_always_delivers(self, executor: JobExecutor):
        job = _make_job(deduplicate=False)
        result = JobResult(success=True, output="same output")

        status, _error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED

        status2, _ = await executor._try_deliver(job, result)
        assert status2 == DeliveryStatus.DELIVERED

    @pytest.mark.asyncio
    async def test_dedup_skips_duplicate(self, executor: JobExecutor):
        output = "Status: all systems normal"
        h = _output_hash(output)
        job = _make_job(deduplicate=True, last_output_hash=h)
        result = JobResult(success=True, output=output)

        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.SKIPPED
        assert error == "duplicate_output"

    @pytest.mark.asyncio
    async def test_dedup_delivers_new_output(self, executor: JobExecutor):
        job = _make_job(deduplicate=True, last_output_hash=_output_hash("old output"))
        result = JobResult(success=True, output="new output")

        status, _ = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED
        assert job.last_output_hash == _output_hash("new output")

    @pytest.mark.asyncio
    async def test_dedup_first_run_delivers(self, executor: JobExecutor):
        """First run (no previous hash) should always deliver."""
        job = _make_job(deduplicate=True, last_output_hash=None)
        result = JobResult(success=True, output="first output")

        status, _ = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED
        assert job.last_output_hash == _output_hash("first output")

    @pytest.mark.asyncio
    async def test_dedup_does_not_update_hash_on_delivery_failure(self, executor: JobExecutor):
        """Hash should NOT update if delivery fails — so next run retries."""
        executor._delivery.deliver = AsyncMock(side_effect=RuntimeError("network error"))
        job = _make_job(deduplicate=True, last_output_hash=None)
        result = JobResult(success=True, output="important output")

        status, _error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.FAILED
        assert job.last_output_hash is None  # not updated

    @pytest.mark.asyncio
    async def test_dedup_skips_silent_before_hash_check(self, executor: JobExecutor):
        """[SILENT] should be checked before dedup hash."""
        job = _make_job(deduplicate=True, last_output_hash=None)
        result = JobResult(success=True, output="[SILENT]")

        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.SKIPPED
        assert error == "silent_response"
        assert job.last_output_hash is None  # hash not updated for silent

    @pytest.mark.asyncio
    async def test_dedup_ignores_failed_results(self, executor: JobExecutor):
        """Dedup only applies to successful results."""
        h = _output_hash("error message")
        job = _make_job(deduplicate=True, last_output_hash=h)
        result = JobResult(success=False, output="error message", error="failed")

        status, _ = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED
