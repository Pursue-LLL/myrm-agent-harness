"""Test cron config validation (defense-in-depth floors & ceilings)."""

import pytest

from myrm_agent_harness.toolkits.cron.types import (
    CronConfig,
    CronJob,
    JobStatus,
    JobType,
    Schedule,
    ScheduleKind,
)


class TestScheduleValidation:
    """Test Schedule config validation."""

    def test_interval_ms_min_floor_100ms(self):
        """interval_ms must be >= 100 to prevent CPU storms."""
        # Valid: exactly 100ms
        schedule = Schedule(kind=ScheduleKind.INTERVAL, interval_ms=100)
        assert schedule.interval_ms == 100

        # Invalid: 99ms (below floor)
        with pytest.raises(ValueError, match="interval_ms must be >= 100"):
            Schedule(kind=ScheduleKind.INTERVAL, interval_ms=99)

        # Invalid: 1ms (CPU storm scenario)
        with pytest.raises(ValueError, match="interval_ms must be >= 100"):
            Schedule(kind=ScheduleKind.INTERVAL, interval_ms=1)

    def test_interval_ms_zero_rejected(self):
        """interval_ms=0 is rejected (was previously allowed as <= 0)."""
        with pytest.raises(ValueError, match="interval_ms must be >= 100"):
            Schedule(kind=ScheduleKind.INTERVAL, interval_ms=0)


class TestCronConfigValidation:
    """Test CronConfig validation."""

    def test_max_concurrent_ceiling_100(self):
        """max_concurrent must be <= 100 to prevent resource exhaustion."""
        # Valid: exactly 100
        config = CronConfig(max_concurrent=100)
        assert config.max_concurrent == 100

        # Invalid: 101 (above ceiling)
        with pytest.raises(ValueError, match="max_concurrent must be <= 100"):
            CronConfig(max_concurrent=101)

        # Invalid: 10000 (OOM scenario)
        with pytest.raises(ValueError, match="max_concurrent must be <= 100"):
            CronConfig(max_concurrent=10000)

    def test_max_per_user_ceiling_100(self):
        """max_per_user must be <= 100 to prevent resource exhaustion."""
        # Valid: exactly 100
        config = CronConfig(max_per_user=100)
        assert config.max_per_user == 100

        # Invalid: 101 (above ceiling)
        with pytest.raises(ValueError, match="max_per_user must be <= 100"):
            CronConfig(max_per_user=101)


class TestCronJobValidation:
    """Test CronJob config validation."""

    def _make_minimal_job(self, **overrides):
        """Helper to create a minimal valid CronJob."""
        defaults = {
            "id": "test-id",
            "user_id": "test-user",
            "name": "test-job",
            "job_type": JobType.AGENT,
            "schedule": Schedule(kind=ScheduleKind.INTERVAL, interval_ms=1000),
            "status": JobStatus.ACTIVE,
            "prompt": "test prompt",
        }
        defaults.update(overrides)
        return CronJob(**defaults)

    def test_timeout_seconds_min_floor_10s(self):
        """timeout_seconds must be >= 10 to prevent alert storms."""
        # Valid: exactly 10s
        job = self._make_minimal_job(timeout_seconds=10)
        assert job.timeout_seconds == 10

        # Invalid: 9s (below floor)
        with pytest.raises(ValueError, match="timeout_seconds must be >= 10"):
            self._make_minimal_job(timeout_seconds=9)

        # Invalid: 1s (alert storm scenario)
        with pytest.raises(ValueError, match="timeout_seconds must be >= 10"):
            self._make_minimal_job(timeout_seconds=1)

    def test_retry_backoff_ms_min_floor_100ms(self):
        """retry_backoff_ms must be >= 100 to prevent service overload."""
        # Valid: exactly 100ms
        job = self._make_minimal_job(retry_backoff_ms=100)
        assert job.retry_backoff_ms == 100

        # Invalid: 99ms (below floor)
        with pytest.raises(ValueError, match="retry_backoff_ms must be >= 100"):
            self._make_minimal_job(retry_backoff_ms=99)

        # Invalid: 1ms (service overload scenario)
        with pytest.raises(ValueError, match="retry_backoff_ms must be >= 100"):
            self._make_minimal_job(retry_backoff_ms=1)

    def test_max_retries_ceiling_10(self):
        """max_retries must be <= 10 to prevent resource waste."""
        # Valid: exactly 10
        job = self._make_minimal_job(max_retries=10)
        assert job.max_retries == 10

        # Invalid: 11 (above ceiling)
        with pytest.raises(ValueError, match="max_retries must be <= 10"):
            self._make_minimal_job(max_retries=11)

        # Invalid: 1000 (resource waste scenario)
        with pytest.raises(ValueError, match="max_retries must be <= 10"):
            self._make_minimal_job(max_retries=1000)

    def test_max_fires_min_floor_1(self):
        """max_fires must be >= 1 when specified (prevent logic errors)."""
        # Valid: None (unlimited)
        job = self._make_minimal_job(max_fires=None)
        assert job.max_fires is None

        # Valid: exactly 1
        job = self._make_minimal_job(max_fires=1)
        assert job.max_fires == 1

        # Invalid: 0 (logic error)
        with pytest.raises(ValueError, match="max_fires must be >= 1"):
            self._make_minimal_job(max_fires=0)

        # Invalid: negative (logic error)
        with pytest.raises(ValueError, match="max_fires must be >= 1"):
            self._make_minimal_job(max_fires=-1)


class TestConfigRejectionStrategy:
    """Test 'reject entire config on violation' (no partial trust)."""

    def test_schedule_rejects_entire_config_on_violation(self):
        """If interval_ms is invalid, entire Schedule is rejected."""
        # Simulate user config with one bad field
        with pytest.raises(ValueError, match="interval_ms must be >= 100"):
            Schedule(
                kind=ScheduleKind.INTERVAL,
                interval_ms=1,  # Bad: CPU storm
                stagger_ms=5000,  # Good: valid stagger
            )
        # No partial trust: stagger_ms is NOT silently accepted

    def test_cronjob_rejects_entire_config_on_violation(self):
        """If timeout_seconds is invalid, entire CronJob is rejected."""
        # Simulate user config with one bad field
        with pytest.raises(ValueError, match="timeout_seconds must be >= 10"):
            CronJob(
                id="test-id",
                user_id="test-user",
                name="test-job",
                job_type=JobType.AGENT,
                schedule=Schedule(kind=ScheduleKind.INTERVAL, interval_ms=1000),
                status=JobStatus.ACTIVE,
                prompt="test prompt",
                timeout_seconds=1,  # Bad: alert storm
                max_retries=5,  # Good: valid retries
                retry_backoff_ms=5000,  # Good: valid backoff
            )
        # No partial trust: max_retries and retry_backoff_ms are NOT silently accepted
