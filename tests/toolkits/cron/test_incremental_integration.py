"""Integration tests for incremental monitoring in cron executor."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from myrm_agent_harness.infra.incremental.types import MonitorConfig, MonitorState
from myrm_agent_harness.toolkits.cron.engine.executor import JobExecutor
from myrm_agent_harness.toolkits.cron.types import (
    CronJob,
    DeliveryConfig,
    JobResult,
    JobType,
    Schedule,
    ScheduleKind,
)


class TestIncrementalIntegration:
    """Test incremental monitoring integration with JobExecutor."""

    @pytest.fixture
    def mock_store(self) -> Mock:
        """Create mock CronStore."""
        store = Mock()
        store.get_job = AsyncMock(return_value=None)
        store.get_monitor_state = AsyncMock(return_value=None)
        store.save_monitor_state = AsyncMock()
        store.save_run = AsyncMock()
        store.save_job = AsyncMock()
        store.get_latest_integrity_hash = AsyncMock(return_value=None)
        return store

    @pytest.fixture
    def mock_delivery(self) -> Mock:
        """Create mock ResultDelivery."""
        delivery = Mock()
        delivery.deliver = AsyncMock()
        return delivery

    @pytest.fixture
    def executor(self, mock_store: Mock, mock_delivery: Mock) -> JobExecutor:
        """Create JobExecutor with mocks."""
        return JobExecutor(
            store=mock_store,
            delivery=mock_delivery,
        )

    @pytest.fixture
    def job_with_monitor(self) -> CronJob:
        """Create test job with monitoring enabled."""
        return CronJob(
            id="test-job",
            user_id="user1",
            name="RSS Monitor",
            job_type=JobType.SHELL,
            schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=3600000),
            command="echo 'url1\nurl2\nurl3'",
            monitor_config=MonitorConfig(
                monitor_type="set",
                ttl_days=30,
                enabled=True,
            ),
            delivery=DeliveryConfig(channel="chat"),
        )

    async def test_baseline_run_skips_delivery(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_delivery: Mock,
    ) -> None:
        """Baseline run should skip delivery (exit_code=0)."""
        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=True,
                output="url1\nurl2\nurl3",
                exit_code=0,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        mock_delivery.deliver.assert_not_called()

    async def test_new_content_triggers_delivery(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_delivery: Mock,
        mock_store: Mock,
    ) -> None:
        """New content should trigger delivery with delta."""
        state_data = {
            "seen": ["url1", "url2"],
            "is_baseline": False,
        }
        from myrm_agent_harness.infra.incremental.types import MonitorState

        mock_store.get_monitor_state.return_value = MonitorState(
            job_id="test-job",
            monitor_type="set",
            data=state_data,
            updated_at=datetime.now(UTC),
            ttl_days=30,
        )

        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=True,
                output="url1\nurl2\nurl3\nurl4",
                exit_code=0,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        mock_delivery.deliver.assert_called_once()
        delivered_result = mock_delivery.deliver.call_args[0][1]
        assert "url3" in delivered_result.output
        assert "url4" in delivered_result.output
        assert "url1" not in delivered_result.output

    async def test_no_new_content_skips_delivery(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_delivery: Mock,
        mock_store: Mock,
    ) -> None:
        """No new content should skip delivery."""
        state_data = {
            "seen": ["url1", "url2", "url3"],
            "is_baseline": False,
        }
        from myrm_agent_harness.infra.incremental.types import MonitorState

        mock_store.get_monitor_state.return_value = MonitorState(
            job_id="test-job",
            monitor_type="set",
            data=state_data,
            updated_at=datetime.now(UTC),
            ttl_days=30,
        )

        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=True,
                output="url1\nurl2\nurl3",
                exit_code=0,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        mock_delivery.deliver.assert_not_called()

    async def test_monitor_disabled_uses_full_output(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_delivery: Mock,
    ) -> None:
        """Disabled monitoring should deliver full output."""
        job_with_monitor.monitor_config = MonitorConfig(
            monitor_type="set",
            ttl_days=30,
            enabled=False,
        )

        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=True,
                output="url1\nurl2\nurl3",
                exit_code=0,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        mock_delivery.deliver.assert_called_once()
        delivered_result = mock_delivery.deliver.call_args[0][1]
        assert delivered_result.output == "url1\nurl2\nurl3"

    async def test_error_result_skips_monitoring(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_delivery: Mock,
        mock_store: Mock,
    ) -> None:
        """Error results should skip monitoring."""
        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=False,
                output="",
                error="command failed",
                exit_code=2,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        mock_store.get_monitor_state.assert_not_called()
        mock_store.save_monitor_state.assert_not_called()

    async def test_monitor_state_persisted_after_run(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_store: Mock,
    ) -> None:
        """Monitor state should be persisted after successful run."""
        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=True,
                output="url1\nurl2\nurl3",
                exit_code=0,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        mock_store.save_monitor_state.assert_called_once()
        saved_state = mock_store.save_monitor_state.call_args[0][0]
        assert saved_state.job_id == "test-job"
        assert saved_state.monitor_type == "set"

    async def test_monitoring_failure_records_failure_count(
        self,
        job_with_monitor: CronJob,
        mock_store: Mock,
        mock_delivery: Mock,
    ) -> None:
        """Monitoring failures should be recorded with incrementing count."""
        storage: dict[str, MonitorState] = {}

        mock_store.get_monitor_state = AsyncMock(side_effect=lambda job_id: storage.get(job_id))
        mock_store.save_monitor_state = AsyncMock(side_effect=lambda state: storage.update({state.job_id: state}))

        executor = JobExecutor(mock_store, mock_delivery)
        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(success=True, output="invalid\noutput\n" + "x" * 1000000, exit_code=0)
        )

        from unittest.mock import patch

        with patch.object(
            executor._monitor_manager,
            "get_monitor",
            side_effect=ValueError("Simulated monitor failure"),
        ):
            await executor.run_and_record(job_with_monitor, runner)

        assert "test-job" in storage
        assert storage["test-job"].failure_count == 1

    async def test_consecutive_failures_trigger_error_log(
        self,
        job_with_monitor: CronJob,
        mock_delivery: Mock,
        caplog: object,
    ) -> None:
        """3+ consecutive failures should trigger ERROR level log."""
        storage: dict[str, MonitorState] = {}

        mock_store = Mock()
        mock_store.get_job = AsyncMock(return_value=None)
        mock_store.get_monitor_state = AsyncMock(side_effect=lambda job_id: storage.get(job_id))
        mock_store.save_monitor_state = AsyncMock(side_effect=lambda state: storage.update({state.job_id: state}))
        mock_store.save_run = AsyncMock()
        mock_store.update_job_runtime_state = AsyncMock()
        mock_store.get_latest_integrity_hash = AsyncMock(return_value=None)
        mock_store.save_job = AsyncMock()

        executor = JobExecutor(mock_store, mock_delivery)
        runner = Mock()
        runner.run = AsyncMock(return_value=JobResult(success=True, output="url1", exit_code=0))

        import logging

        with caplog.at_level(logging.ERROR):
            from unittest.mock import patch

            with patch.object(
                executor._monitor_manager,
                "get_monitor",
                side_effect=ValueError("Simulated monitor error"),
            ):
                for _ in range(3):
                    await executor.run_and_record(job_with_monitor, runner)

                assert "failed 3 times consecutively" in caplog.text

    async def test_baseline_reset_adds_metadata(
        self,
        executor: JobExecutor,
        job_with_monitor: CronJob,
        mock_store: Mock,
        mock_delivery: Mock,
    ) -> None:
        """TTL-expired baseline reset should add metadata and deliver."""
        from datetime import UTC, datetime, timedelta

        from myrm_agent_harness.infra.incremental.types import MonitorState

        expired_state = MonitorState(
            job_id="test-job",
            monitor_type="set",
            data={"seen": ["old1", "old2"]},
            updated_at=datetime.now(UTC) - timedelta(days=35),
            ttl_days=30,
        )

        mock_store.get_monitor_state.return_value = expired_state

        runner = Mock()
        runner.run = AsyncMock(
            return_value=JobResult(
                success=True,
                output="url1\nurl2",
                exit_code=0,
            )
        )

        await executor.run_and_record(job_with_monitor, runner)

        delivered_result = mock_delivery.deliver.call_args[0][1]
        assert delivered_result.metadata is not None
        assert delivered_result.metadata.get("baseline_reset") is True
        assert delivered_result.metadata.get("reset_reason") == "ttl_expired"
