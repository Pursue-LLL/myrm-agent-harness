"""Unit tests for JobExecutor — delivery, state update, and failure alerting."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.observability.tracing import TracingContext
from myrm_agent_harness.toolkits.cron.engine.executor import JobExecutor, _output_hash
from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    DeliveryConfig,
    DeliveryStatus,
    FailureAlertConfig,
    JobResult,
    JobStatus,
    JobType,
    RunStatus,
    Schedule,
    ScheduleKind,
)


def _make_schedule(kind: ScheduleKind = ScheduleKind.CRON) -> Schedule:
    if kind == ScheduleKind.ONCE:
        return Schedule(kind=kind, run_at=datetime.now(UTC) + timedelta(hours=1))
    return Schedule(kind=kind, expr="0 * * * *")


def _make_job(**overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "id": "job-1",
        "user_id": "user-1",
        "name": "Test Job",
        "job_type": JobType.AGENT,
        "schedule": _make_schedule(),
        "status": JobStatus.ACTIVE,
        "prompt": "test prompt",
        "delivery": DeliveryConfig(channel="chat"),
    }
    defaults.update(overrides)
    return CronJob(**defaults)  # type: ignore[arg-type]


def _make_executor(
    *,
    config: CronConfig | None = None,
    push_callback: AsyncMock | None = None,
) -> tuple[JobExecutor, AsyncMock, AsyncMock]:
    store = AsyncMock()
    store.save_job = AsyncMock(side_effect=lambda j: j)
    store.save_run = AsyncMock()
    store.delete_job = AsyncMock(return_value=True)
    store.get_latest_integrity_hash = AsyncMock(return_value=None)
    store.get_job = AsyncMock(side_effect=lambda job_id: _make_job(id=job_id))
    delivery = AsyncMock()
    delivery.deliver = AsyncMock()
    executor = JobExecutor(
        store=store,
        delivery=delivery,
        config=config,
        push_callback=push_callback,
    )
    return executor, store, delivery


# ---------------------------------------------------------------------------
# _output_hash
# ---------------------------------------------------------------------------


class TestOutputHash:
    def test_deterministic(self) -> None:
        h1 = _output_hash("hello world")
        h2 = _output_hash("hello world")
        assert h1 == h2
        assert len(h1) == 32

    def test_strips_whitespace(self) -> None:
        assert _output_hash("  hello  ") == _output_hash("hello")


# ---------------------------------------------------------------------------
# _try_deliver
# ---------------------------------------------------------------------------


class TestTryDeliver:
    @pytest.mark.asyncio
    async def test_skip_none_channel(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job(delivery=DeliveryConfig(channel="none"))
        result = JobResult(success=True, output="hi")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.SKIPPED
        assert error is None

    @pytest.mark.asyncio
    async def test_silent_response_skipped(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job()
        result = JobResult(success=True, output="[SILENT]")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.SKIPPED
        assert error == "silent_response"

    @pytest.mark.asyncio
    async def test_empty_success_output_skipped(self) -> None:
        executor, _, delivery = _make_executor()
        job = _make_job()
        result = JobResult(success=True, output="   ")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.SKIPPED
        assert error == "empty_output"
        delivery.deliver.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_silent_with_suffix_delivers(self) -> None:
        executor, _, delivery = _make_executor()
        job = _make_job()
        result = JobResult(success=True, output="[SILENT] nothing to report")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED
        assert error is None
        delivery.deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delivery_success(self) -> None:
        executor, _, delivery = _make_executor()
        job = _make_job()
        result = JobResult(success=True, output="some output")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED
        assert error is None
        delivery.deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delivery_failure(self) -> None:
        executor, _, delivery = _make_executor()
        delivery.deliver = AsyncMock(side_effect=RuntimeError("network error"))
        job = _make_job()
        result = JobResult(success=True, output="some output")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.FAILED
        assert "network error" in (error or "")

    @pytest.mark.asyncio
    async def test_duplicate_output_skipped(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job(deduplicate=True, last_output_hash=_output_hash("same output"))
        result = JobResult(success=True, output="same output")
        status, error = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.SKIPPED
        assert error == "duplicate_output"

    @pytest.mark.asyncio
    async def test_incremental_delta_delivered(self) -> None:
        executor, _, delivery = _make_executor()
        job = _make_job()
        result = JobResult(
            success=True,
            output="full output here",
            incremental_delta="only the new part",
        )
        status, _ = await executor._try_deliver(job, result)
        assert status == DeliveryStatus.DELIVERED
        delivered_result = delivery.deliver.call_args[0][1]
        assert delivered_result.output == "only the new part"

    @pytest.mark.asyncio
    async def test_dedup_hash_updated_after_delivery(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job(deduplicate=True, last_output_hash=None)
        result = JobResult(success=True, output="new output")
        await executor._try_deliver(job, result)
        assert job.last_output_hash == _output_hash("new output")


# ---------------------------------------------------------------------------
# _push_notification
# ---------------------------------------------------------------------------


class TestPushNotification:
    @pytest.mark.asyncio
    async def test_no_callback(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job()
        result = JobResult(success=True, output="hi")
        await executor._push_notification(job, result, DeliveryStatus.DELIVERED)

    @pytest.mark.asyncio
    async def test_skipped_delivery_no_push(self) -> None:
        cb = AsyncMock()
        executor, _, _ = _make_executor(push_callback=cb)
        job = _make_job()
        result = JobResult(success=True, output="hi")
        await executor._push_notification(job, result, DeliveryStatus.SKIPPED)
        cb.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_success_push(self) -> None:
        cb = AsyncMock()
        executor, _, _ = _make_executor(push_callback=cb)
        job = _make_job()
        result = JobResult(success=True, output="hello world")
        await executor._push_notification(job, result, DeliveryStatus.DELIVERED)
        cb.assert_awaited_once()
        args = cb.call_args[0]
        assert args[0] == "user-1"
        assert "success" in args[3]

    @pytest.mark.asyncio
    async def test_error_push(self) -> None:
        cb = AsyncMock()
        executor, _, _ = _make_executor(push_callback=cb)
        job = _make_job()
        result = JobResult(success=False, error="something broke")
        await executor._push_notification(job, result, DeliveryStatus.DELIVERED)
        cb.assert_awaited_once()
        assert "error" in cb.call_args[0][3]

    @pytest.mark.asyncio
    async def test_push_failure_logged(self) -> None:
        cb = AsyncMock(side_effect=RuntimeError("push failed"))
        executor, _, _ = _make_executor(push_callback=cb)
        job = _make_job()
        result = JobResult(success=True, output="hi")
        await executor._push_notification(job, result, DeliveryStatus.DELIVERED)


# ---------------------------------------------------------------------------
# _update_after_run — recurring jobs
# ---------------------------------------------------------------------------


class TestUpdateAfterRunRecurring:
    @pytest.mark.asyncio
    async def test_success_schedules_next(self) -> None:
        executor, store, _ = _make_executor()
        job = _make_job(consecutive_failures=2)
        result = JobResult(success=True, output="ok")
        now = datetime.now(UTC)
        await executor._update_after_run(job, result, 0, now)
        assert job.next_run_at is not None
        assert job.last_status == RunStatus.OK
        assert job.consecutive_failures == 0
        assert job.last_failure_alert_at is None
        store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_failure_within_retries_uses_backoff(self) -> None:
        executor, _store, _ = _make_executor()
        job = _make_job(max_retries=3)
        result = JobResult(success=False, error="oops")
        now = datetime.now(UTC)
        await executor._update_after_run(job, result, 1, now)
        assert job.status == JobStatus.ACTIVE
        assert job.next_run_at is not None
        assert job.next_run_at > now
        assert job.last_status == RunStatus.ERROR

    @pytest.mark.asyncio
    async def test_failure_exceeds_retries_pauses(self) -> None:
        executor, _store, _ = _make_executor()
        job = _make_job(max_retries=2)
        result = JobResult(success=False, error="persistent error")
        now = datetime.now(UTC)
        await executor._update_after_run(job, result, 3, now)
        assert job.status == JobStatus.PAUSED
        assert job.next_run_at is None

    @pytest.mark.asyncio
    async def test_deleted_job_skips_update(self) -> None:
        """Job deleted during execution: _update_after_run should silently skip."""
        executor, store, _ = _make_executor()
        store.get_job = AsyncMock(return_value=None)
        job = _make_job()
        result = JobResult(success=True, output="ok")
        await executor._update_after_run(job, result, 0, datetime.now(UTC))
        store.save_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deleted_once_job_skips_update(self) -> None:
        """One-shot job deleted during execution: should silently skip."""
        executor, store, _ = _make_executor()
        store.get_job = AsyncMock(return_value=None)
        job = _make_job(schedule=_make_schedule(ScheduleKind.ONCE))
        result = JobResult(success=True, output="done")
        await executor._update_after_run(job, result, 0, datetime.now(UTC))
        store.save_job.assert_not_awaited()
        store.delete_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_job_store_error_propagates(self) -> None:
        """Store failure on get_job should propagate, not be swallowed."""
        executor, store, _ = _make_executor()
        store.get_job = AsyncMock(side_effect=RuntimeError("db connection lost"))
        job = _make_job()
        result = JobResult(success=True, output="ok")
        with pytest.raises(RuntimeError, match="db connection lost"):
            await executor._update_after_run(job, result, 0, datetime.now(UTC))
        store.save_job.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_deleted_failed_job_skips_update(self) -> None:
        """Failed job deleted during execution: should skip (no resurrection)."""
        executor, store, _ = _make_executor()
        store.get_job = AsyncMock(return_value=None)
        job = _make_job(max_retries=3)
        result = JobResult(success=False, error="error")
        await executor._update_after_run(job, result, 1, datetime.now(UTC))
        store.save_job.assert_not_awaited()


# ---------------------------------------------------------------------------
# _handle_once_completion
# ---------------------------------------------------------------------------


class TestHandleOnceCompletion:
    @pytest.mark.asyncio
    async def test_success_delete_after_run(self) -> None:
        executor, store, _ = _make_executor()
        job = _make_job(
            schedule=_make_schedule(ScheduleKind.ONCE),
            delete_after_run=True,
        )
        result = JobResult(success=True, output="done")
        await executor._handle_once_completion(job, result, 0, datetime.now(UTC))
        store.delete_job.assert_awaited_once_with("job-1")

    @pytest.mark.asyncio
    async def test_success_no_delete(self) -> None:
        executor, store, _ = _make_executor()
        job = _make_job(
            schedule=_make_schedule(ScheduleKind.ONCE),
            delete_after_run=False,
        )
        result = JobResult(success=True, output="done")
        await executor._handle_once_completion(job, result, 0, datetime.now(UTC))
        assert job.status == JobStatus.COMPLETED
        assert job.next_run_at is None
        store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transient_error_retries(self) -> None:
        executor, _store, _ = _make_executor()
        job = _make_job(
            schedule=_make_schedule(ScheduleKind.ONCE),
            max_retries=3,
        )
        result = JobResult(success=False, error="rate limit exceeded")
        now = datetime.now(UTC)
        await executor._handle_once_completion(job, result, 1, now)
        assert job.status == JobStatus.ACTIVE
        assert job.next_run_at is not None
        assert job.next_run_at > now

    @pytest.mark.asyncio
    async def test_permanent_error_pauses(self) -> None:
        executor, _store, _ = _make_executor()
        job = _make_job(
            schedule=_make_schedule(ScheduleKind.ONCE),
            max_retries=2,
        )
        result = JobResult(success=False, error="some permanent error xyz")
        now = datetime.now(UTC)
        await executor._handle_once_completion(job, result, 3, now)
        assert job.status == JobStatus.PAUSED
        assert job.next_run_at is None


# ---------------------------------------------------------------------------
# _handle_schedule_compute_error
# ---------------------------------------------------------------------------


class TestHandleScheduleComputeError:
    def test_below_threshold_sets_fallback(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job(consecutive_failures=0)
        finished = datetime.now(UTC)
        executor._handle_schedule_compute_error(job, ValueError("bad cron"), finished)
        assert job.status == JobStatus.ACTIVE
        assert job.consecutive_failures == 1
        assert job.next_run_at is not None
        assert job.next_run_at == finished + timedelta(seconds=60)

    def test_at_threshold_pauses(self) -> None:
        executor, _, _ = _make_executor()
        job = _make_job(consecutive_failures=2)
        finished = datetime.now(UTC)
        executor._handle_schedule_compute_error(job, ValueError("bad cron"), finished)
        assert job.status == JobStatus.PAUSED
        assert job.next_run_at is None


# ---------------------------------------------------------------------------
# _maybe_send_failure_alert
# ---------------------------------------------------------------------------


class TestMaybeSendFailureAlert:
    def test_no_alert_config(self) -> None:
        executor, _, _delivery = _make_executor()
        job = _make_job(failure_alert=None)
        now = datetime.now(UTC)
        executor._maybe_send_failure_alert(job, 3, now)
        assert job.last_failure_alert_at is None

    @pytest.mark.asyncio
    async def test_alert_sent(self) -> None:
        executor, _, _delivery = _make_executor(config=CronConfig(failure_alert=FailureAlertConfig(after=2)))
        job = _make_job(failure_alert=None, consecutive_failures=3)
        now = datetime.now(UTC)
        executor._maybe_send_failure_alert(job, 3, now)
        assert job.last_failure_alert_at == now

    @pytest.mark.asyncio
    async def test_alert_with_custom_delivery(self) -> None:
        custom = DeliveryConfig(channel="webhook", target="https://alert.example.com")
        executor, _, _delivery = _make_executor(
            config=CronConfig(failure_alert=FailureAlertConfig(after=1, delivery=custom))
        )
        job = _make_job(failure_alert=None, consecutive_failures=3)
        now = datetime.now(UTC)
        executor._maybe_send_failure_alert(job, 3, now)
        assert job.last_failure_alert_at == now


# ---------------------------------------------------------------------------
# run_and_record — full lifecycle
# ---------------------------------------------------------------------------


class TestRunAndRecord:
    @pytest.mark.asyncio
    async def test_success_flow(self) -> None:
        executor, store, _delivery = _make_executor()
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=JobResult(success=True, output="result"))
        await executor.run_and_record(job, runner)
        runner.run.assert_awaited_once_with(job, context="")
        store.save_run.assert_awaited_once()
        store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_timeout_flow(self) -> None:
        executor, store, _delivery = _make_executor()
        job = _make_job(timeout_seconds=10)
        runner = AsyncMock()

        async def slow_run(_: CronJob, **_kw: object) -> JobResult:
            await asyncio.sleep(100)
            return JobResult(success=True, output="never")

        runner.run = slow_run
        with patch("asyncio.wait_for", side_effect=TimeoutError):
            await executor.run_and_record(job, runner)
        saved_run = store.save_run.call_args[0][0]
        assert saved_run.status == RunStatus.ERROR
        assert "timed out" in (saved_run.error or "")

    @pytest.mark.asyncio
    async def test_monitor_no_new_content_skips_delivery(self) -> None:
        """When monitor detects no change, exit_code=0 → delivery skipped."""
        executor, _store, delivery = _make_executor()
        from myrm_agent_harness.infra.incremental.types import MonitorConfig

        mc = MonitorConfig(enabled=True, monitor_type="text_diff")
        job = _make_job(monitor_config=mc)
        result = JobResult(success=True, output="same content", exit_code=0)

        runner = AsyncMock()
        runner.run = AsyncMock(return_value=result)

        with patch.object(executor._monitor_manager, "get_monitor") as mock_get:
            mock_monitor = MagicMock()
            mock_monitor.is_baseline.return_value = False
            mock_monitor.compute_delta.return_value = ""
            mock_get.return_value = (mock_monitor, None)

            with patch.object(executor._monitor_manager, "save_monitor_state", new_callable=AsyncMock):
                await executor.run_and_record(job, runner)

        delivery.deliver.assert_not_awaited()


# ---------------------------------------------------------------------------
# _resolve_context_from tests
# ---------------------------------------------------------------------------


class TestResolveContextFrom:
    """Tests for _resolve_context_from: cross-job context injection."""

    @pytest.mark.asyncio
    async def test_empty_context_from_returns_empty(self) -> None:
        """Job with no context_from should produce empty string."""
        executor, _store, _delivery = _make_executor()
        job = _make_job(context_from=())
        result = await executor._resolve_context_from(job)
        assert result == ""

    @pytest.mark.asyncio
    async def test_single_ref_with_output(self) -> None:
        """Single ref with a successful run injects its output."""
        executor, store, _delivery = _make_executor()
        ref_job = _make_job(id="ref-1", name="Stock Monitor")
        run = MagicMock()
        run.output = "AAPL: 150.3"
        store.list_runs = AsyncMock(return_value=[run])
        store.get_job = AsyncMock(return_value=ref_job)

        job = _make_job(context_from=("ref-1",))
        result = await executor._resolve_context_from(job)
        assert "Stock Monitor" in result
        assert "AAPL: 150.3" in result

    @pytest.mark.asyncio
    async def test_ref_with_no_successful_runs_skipped(self) -> None:
        """Ref whose latest runs are empty is silently skipped."""
        executor, store, _delivery = _make_executor()
        store.list_runs = AsyncMock(return_value=[])

        job = _make_job(context_from=("ref-missing-runs",))
        result = await executor._resolve_context_from(job)
        assert result == ""

    @pytest.mark.asyncio
    async def test_ref_with_empty_output_skipped(self) -> None:
        """Ref whose run has None/empty output is skipped."""
        executor, store, _delivery = _make_executor()
        run = MagicMock()
        run.output = ""
        store.list_runs = AsyncMock(return_value=[run])

        job = _make_job(context_from=("ref-empty",))
        result = await executor._resolve_context_from(job)
        assert result == ""

    @pytest.mark.asyncio
    async def test_ref_job_deleted_shows_id_as_fallback(self) -> None:
        """If referenced job is deleted, use job ID as task name."""
        executor, store, _delivery = _make_executor()
        run = MagicMock()
        run.output = "some data"
        store.list_runs = AsyncMock(return_value=[run])
        store.get_job = AsyncMock(return_value=None)

        job = _make_job(context_from=("deleted-ref",))
        result = await executor._resolve_context_from(job)
        assert "deleted-ref" in result
        assert "some data" in result

    @pytest.mark.asyncio
    async def test_output_truncation(self) -> None:
        """Output exceeding _MAX_CONTEXT_FROM_CHARS is truncated."""
        from myrm_agent_harness.toolkits.cron.engine.executor import _MAX_CONTEXT_FROM_CHARS

        executor, store, _delivery = _make_executor()
        long_output = "x" * (_MAX_CONTEXT_FROM_CHARS + 500)
        run = MagicMock()
        run.output = long_output
        ref_job = _make_job(id="ref-long", name="Long Output Task")
        store.list_runs = AsyncMock(return_value=[run])
        store.get_job = AsyncMock(return_value=ref_job)

        job = _make_job(context_from=("ref-long",))
        result = await executor._resolve_context_from(job)
        assert "[... output truncated ...]" in result
        assert len(result) < len(long_output)

    @pytest.mark.asyncio
    async def test_multiple_refs_joined_with_separator(self) -> None:
        """Multiple refs are joined with --- separator."""
        executor, store, _delivery = _make_executor()
        run_a = MagicMock()
        run_a.output = "Data from A"
        run_b = MagicMock()
        run_b.output = "Data from B"

        async def mock_list_runs(job_id: str, **kwargs: object) -> list[MagicMock]:
            return [{"ref-a": run_a, "ref-b": run_b}[job_id]]

        async def mock_get_job(job_id: str) -> CronJob:
            names = {"ref-a": "Task A", "ref-b": "Task B"}
            return _make_job(id=job_id, name=names[job_id])

        store.list_runs = AsyncMock(side_effect=mock_list_runs)
        store.get_job = AsyncMock(side_effect=mock_get_job)

        job = _make_job(context_from=("ref-a", "ref-b"))
        result = await executor._resolve_context_from(job)
        assert "Task A" in result
        assert "Task B" in result
        assert "---" in result
        assert "Data from A" in result
        assert "Data from B" in result

    @pytest.mark.asyncio
    async def test_context_from_injected_into_runner(self) -> None:
        """Verify context_from text is passed to runner.run() as context."""
        executor, store, _delivery = _make_executor()
        run = MagicMock()
        run.output = "injected data"
        ref_job = _make_job(id="ref-1", name="Injector")

        store.list_runs = AsyncMock(return_value=[run])
        store.get_job = AsyncMock(return_value=ref_job)

        runner = AsyncMock()
        runner.run = AsyncMock(return_value=JobResult(success=True, output="done"))

        job = _make_job(context_from=("ref-1",))
        await executor.run_and_record(job, runner)

        call_kwargs = runner.run.call_args
        context_arg = call_kwargs.kwargs.get("context") or call_kwargs[1].get("context", "")
        assert "injected data" in context_arg


# ---------------------------------------------------------------------------
# Runner-level skip (JobResult.skipped)
# ---------------------------------------------------------------------------


class TestRunnerSkip:
    @pytest.mark.asyncio
    async def test_skipped_result_records_skipped_status(self) -> None:
        """Runner returning skipped=True should record SKIPPED, skip delivery."""
        executor, store, delivery = _make_executor()
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=JobResult(success=True, skipped=True, skip_reason="no-content")
        )
        await executor.run_and_record(job, runner)

        saved_run = store.save_run.call_args[0][0]
        assert saved_run.status == RunStatus.SKIPPED
        assert saved_run.delivery_status == DeliveryStatus.SKIPPED
        assert saved_run.output == "no-content"
        delivery.deliver.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skipped_without_reason(self) -> None:
        """Skipped result with no reason should still record SKIPPED."""
        executor, store, _delivery = _make_executor()
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=JobResult(success=True, skipped=True)
        )
        await executor.run_and_record(job, runner)

        saved_run = store.save_run.call_args[0][0]
        assert saved_run.status == RunStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_skipped_advances_schedule(self) -> None:
        """Skipped job should advance next_run_at for recurring schedule."""
        executor, store, _ = _make_executor()
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=JobResult(success=True, skipped=True, skip_reason="no-content")
        )
        await executor.run_and_record(job, runner)

        assert job.last_status == RunStatus.SKIPPED
        assert job.status == JobStatus.ACTIVE
        store.save_job.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skipped_once_with_delete(self) -> None:
        """One-shot job with delete_after_run=True skipped by runner should be deleted."""
        executor, store, _ = _make_executor()
        job = _make_job(
            schedule=_make_schedule(ScheduleKind.ONCE),
            delete_after_run=True,
        )
        runner = AsyncMock()
        runner.run = AsyncMock(
            return_value=JobResult(success=True, skipped=True, skip_reason="no-content")
        )
        await executor.run_and_record(job, runner)

        store.delete_job.assert_awaited_once_with("job-1")


# ---------------------------------------------------------------------------
# TracingContext injection in run_and_record
# ---------------------------------------------------------------------------


class TestRunAndRecordTracing:
    """Verify TracingContext is properly set during execution and reset after."""

    @pytest.mark.asyncio
    async def test_trace_id_set_during_execution(self) -> None:
        """trace_id should be a valid 32-char hex during runner.run()."""
        executor, _store, _delivery = _make_executor()
        job = _make_job()
        captured_trace_id: str = ""

        async def capturing_run(_job: CronJob, **_kw: object) -> JobResult:
            nonlocal captured_trace_id
            captured_trace_id = TracingContext.get_trace_id()
            return JobResult(success=True, output="ok")

        runner = AsyncMock()
        runner.run = capturing_run

        await executor.run_and_record(job, runner)

        assert captured_trace_id != "-"
        assert len(captured_trace_id) == 32
        int(captured_trace_id, 16)  # valid hex

    @pytest.mark.asyncio
    async def test_session_id_set_to_job_id(self) -> None:
        """session_id should equal job.id during execution."""
        executor, _store, _delivery = _make_executor()
        job = _make_job(id="my-cron-job-42")
        captured_session_id: str = ""

        async def capturing_run(_job: CronJob, **_kw: object) -> JobResult:
            nonlocal captured_session_id
            captured_session_id = TracingContext.get_session_id()
            return JobResult(success=True, output="ok")

        runner = AsyncMock()
        runner.run = capturing_run

        await executor.run_and_record(job, runner)

        assert captured_session_id == "my-cron-job-42"

    @pytest.mark.asyncio
    async def test_context_reset_after_success(self) -> None:
        """TracingContext must be reset to defaults after run_and_record completes."""
        executor, _store, _delivery = _make_executor()
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=JobResult(success=True, output="ok"))

        await executor.run_and_record(job, runner)

        assert TracingContext.get_trace_id() == "-"
        assert TracingContext.get_session_id() == "-"

    @pytest.mark.asyncio
    async def test_context_reset_after_runner_exception(self) -> None:
        """TracingContext must be reset even when runner raises an exception."""
        executor, _store, _delivery = _make_executor()
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(side_effect=RuntimeError("unexpected crash"))

        with pytest.raises(RuntimeError, match="unexpected crash"):
            await executor.run_and_record(job, runner)

        assert TracingContext.get_trace_id() == "-"
        assert TracingContext.get_session_id() == "-"

    @pytest.mark.asyncio
    async def test_each_execution_gets_unique_trace_id(self) -> None:
        """Consecutive calls to run_and_record produce distinct trace_ids."""
        executor, _store, _delivery = _make_executor()
        captured_ids: list[str] = []

        async def capturing_run(_job: CronJob, **_kw: object) -> JobResult:
            captured_ids.append(TracingContext.get_trace_id())
            return JobResult(success=True, output="ok")

        runner = AsyncMock()
        runner.run = capturing_run
        job = _make_job()

        await executor.run_and_record(job, runner)
        await executor.run_and_record(job, runner)

        assert len(captured_ids) == 2
        assert captured_ids[0] != captured_ids[1]

    @pytest.mark.asyncio
    async def test_context_reset_after_timeout(self) -> None:
        """TracingContext resets after job timeout (TimeoutError path)."""
        executor, _store, _delivery = _make_executor()
        job = _make_job(timeout_seconds=10)

        async def slow_run(_job: CronJob, **_kw: object) -> JobResult:
            await asyncio.sleep(100)
            return JobResult(success=True, output="never")

        runner = AsyncMock()
        runner.run = slow_run

        with patch("asyncio.wait_for", side_effect=TimeoutError):
            await executor.run_and_record(job, runner)

        assert TracingContext.get_trace_id() == "-"
        assert TracingContext.get_session_id() == "-"

    @pytest.mark.asyncio
    async def test_trace_active_during_skipped_runner(self) -> None:
        """trace_id is set during runner execution even when result is skipped."""
        executor, _store, _delivery = _make_executor()
        job = _make_job()
        captured_trace_id: str = ""

        async def skip_run(_job: CronJob, **_kw: object) -> JobResult:
            nonlocal captured_trace_id
            captured_trace_id = TracingContext.get_trace_id()
            return JobResult(success=True, skipped=True, skip_reason="no-content")

        runner = AsyncMock()
        runner.run = skip_run

        await executor.run_and_record(job, runner)

        assert captured_trace_id != "-"
        assert len(captured_trace_id) == 32
        assert TracingContext.get_trace_id() == "-"

    @pytest.mark.asyncio
    async def test_context_reset_after_store_exception(self) -> None:
        """TracingContext resets even when store.save_run raises."""
        executor, store, _delivery = _make_executor()
        store.save_run = AsyncMock(side_effect=RuntimeError("DB connection lost"))
        job = _make_job()
        runner = AsyncMock()
        runner.run = AsyncMock(return_value=JobResult(success=True, output="ok"))

        with pytest.raises(RuntimeError, match="DB connection lost"):
            await executor.run_and_record(job, runner)

        assert TracingContext.get_trace_id() == "-"
        assert TracingContext.get_session_id() == "-"
