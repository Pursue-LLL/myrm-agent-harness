"""Unit tests for startup performance monitoring.

Tests StartupTimer and StartupMetrics with 80%+ coverage.
"""

import asyncio
import time

import pytest

from myrm_agent_harness.runtime.startup import StartupMetrics, StartupTimer


class TestStartupMetrics:
    """Test StartupMetrics dataclass."""

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        metrics = StartupMetrics()

        assert metrics.phase_timings == {}
        assert metrics.task_timings == {}
        assert metrics._start_time > 0

    def test_total_elapsed_ms(self) -> None:
        """Test total_elapsed_ms calculation."""
        metrics = StartupMetrics()

        # Sleep a bit to ensure measurable time
        time.sleep(0.01)

        elapsed = metrics.total_elapsed_ms()
        assert elapsed >= 10.0  # At least 10ms
        assert elapsed < 100.0  # But not too much

    def test_to_dict_empty(self) -> None:
        """Test to_dict with no data."""
        metrics = StartupMetrics()
        result = metrics.to_dict()

        assert "phases" in result
        assert "total_elapsed_ms" in result
        assert result["phases"] == {}
        assert result["total_elapsed_ms"] > 0

    def test_to_dict_with_phase_only(self) -> None:
        """Test to_dict with phase timings only."""
        metrics = StartupMetrics()
        metrics.phase_timings["critical"] = 150.5
        metrics.phase_timings["core"] = 50.3

        result = metrics.to_dict()

        assert result["phases"]["critical"]["total_ms"] == 150.5
        assert result["phases"]["critical"]["tasks"] == {}
        assert result["phases"]["core"]["total_ms"] == 50.3
        assert result["phases"]["core"]["tasks"] == {}

    def test_to_dict_with_tasks(self) -> None:
        """Test to_dict with nested task timings."""
        metrics = StartupMetrics()
        metrics.phase_timings["critical"] = 150.0
        metrics.task_timings["critical"] = {
            "init_database": 10.0,
            "migrate_configs": 50.0,
            "ensure_local_admin": 30.0,
        }

        result = metrics.to_dict()

        assert result["phases"]["critical"]["total_ms"] == 150.0
        assert result["phases"]["critical"]["tasks"] == {
            "init_database": 10.0,
            "migrate_configs": 50.0,
            "ensure_local_admin": 30.0,
        }

    def test_to_dict_does_not_mutate(self) -> None:
        """Test to_dict returns a copy, not original data."""
        metrics = StartupMetrics()
        metrics.phase_timings["critical"] = 150.0
        metrics.task_timings["critical"] = {"init_database": 10.0}

        result = metrics.to_dict()

        # Mutate returned dict
        result["phases"]["critical"]["tasks"]["new_task"] = 99.9

        # Original should be unchanged
        assert "new_task" not in metrics.task_timings["critical"]


class TestStartupTimer:
    """Test StartupTimer async context manager."""

    @pytest.mark.asyncio
    async def test_init(self) -> None:
        """Test timer initialization."""
        timer = StartupTimer()

        assert isinstance(timer.metrics, StartupMetrics)
        assert timer._current_phase is None

    @pytest.mark.asyncio
    async def test_single_phase(self) -> None:
        """Test tracking a single phase."""
        timer = StartupTimer()

        async with timer.phase("critical"):
            await asyncio.sleep(0.01)

        assert "critical" in timer.metrics.phase_timings
        assert timer.metrics.phase_timings["critical"] >= 10.0
        assert timer._current_phase is None  # Reset after exit

    @pytest.mark.asyncio
    async def test_multiple_phases(self) -> None:
        """Test tracking multiple phases."""
        timer = StartupTimer()

        async with timer.phase("critical"):
            await asyncio.sleep(0.01)

        async with timer.phase("core"):
            await asyncio.sleep(0.01)

        async with timer.phase("warmup"):
            await asyncio.sleep(0.01)

        assert "critical" in timer.metrics.phase_timings
        assert "core" in timer.metrics.phase_timings
        assert "warmup" in timer.metrics.phase_timings

        assert timer.metrics.phase_timings["critical"] >= 10.0
        assert timer.metrics.phase_timings["core"] >= 10.0
        assert timer.metrics.phase_timings["warmup"] >= 10.0

    @pytest.mark.asyncio
    async def test_task_within_phase(self) -> None:
        """Test tracking tasks within a phase."""
        timer = StartupTimer()

        async with timer.phase("critical"):
            async with timer.task("init_database"):
                await asyncio.sleep(0.01)

            async with timer.task("migrate_configs"):
                await asyncio.sleep(0.01)

        assert "critical" in timer.metrics.phase_timings
        assert "critical" in timer.metrics.task_timings

        tasks = timer.metrics.task_timings["critical"]
        assert "init_database" in tasks
        assert "migrate_configs" in tasks

        assert tasks["init_database"] >= 10.0
        assert tasks["migrate_configs"] >= 10.0

    @pytest.mark.asyncio
    async def test_task_without_phase_raises(self) -> None:
        """Test task() raises if called outside phase()."""
        timer = StartupTimer()

        with pytest.raises(RuntimeError, match="task\\(\\) must be called within a phase\\(\\) context"):
            async with timer.task("orphan_task"):
                pass

    @pytest.mark.asyncio
    async def test_nested_phases(self) -> None:
        """Test nested phase contexts (inner phase should override)."""
        timer = StartupTimer()

        async with timer.phase("outer"):
            await asyncio.sleep(0.01)

            async with timer.phase("inner"):
                await asyncio.sleep(0.01)

            await asyncio.sleep(0.01)

        assert "outer" in timer.metrics.phase_timings
        assert "inner" in timer.metrics.phase_timings

        # Outer phase should include time for inner phase
        assert timer.metrics.phase_timings["outer"] >= timer.metrics.phase_timings["inner"]

        # After exit, should restore to None (not "outer")
        assert timer._current_phase is None

    @pytest.mark.asyncio
    async def test_task_in_nested_phases(self) -> None:
        """Test tasks are tracked in the correct phase when nested."""
        timer = StartupTimer()

        async with timer.phase("outer"):
            async with timer.task("outer_task"):
                await asyncio.sleep(0.01)

            async with timer.phase("inner"), timer.task("inner_task"):
                await asyncio.sleep(0.01)

        assert "outer_task" in timer.metrics.task_timings["outer"]
        assert "inner_task" in timer.metrics.task_timings["inner"]
        assert "inner_task" not in timer.metrics.task_timings["outer"]

    @pytest.mark.asyncio
    async def test_exception_in_phase(self) -> None:
        """Test phase timing is recorded even if exception occurs."""
        timer = StartupTimer()

        with pytest.raises(ValueError):
            async with timer.phase("critical"):
                await asyncio.sleep(0.01)
                raise ValueError("test error")

        # Timing should still be recorded
        assert "critical" in timer.metrics.phase_timings
        assert timer.metrics.phase_timings["critical"] >= 10.0
        assert timer._current_phase is None

    @pytest.mark.asyncio
    async def test_exception_in_task(self) -> None:
        """Test task timing is recorded even if exception occurs."""
        timer = StartupTimer()

        with pytest.raises(ValueError):
            async with timer.phase("critical"):
                async with timer.task("failing_task"):
                    await asyncio.sleep(0.01)
                    raise ValueError("test error")

        # Both phase and task timing should be recorded
        assert "critical" in timer.metrics.phase_timings
        assert "failing_task" in timer.metrics.task_timings["critical"]
        assert timer.metrics.task_timings["critical"]["failing_task"] >= 10.0

    @pytest.mark.asyncio
    async def test_complex_workflow(self) -> None:
        """Test a complex realistic workflow."""
        timer = StartupTimer()

        # Phase 1: Critical
        async with timer.phase("critical"):
            async with timer.task("init_database"):
                await asyncio.sleep(0.01)
            async with timer.task("migrate_configs"):
                await asyncio.sleep(0.01)
            async with timer.task("ensure_local_admin"):
                await asyncio.sleep(0.01)

        # Phase 2: Core
        async with timer.phase("core"):
            async with timer.task("start_channel_gateway"):
                await asyncio.sleep(0.01)
            async with timer.task("start_cron_scheduler"):
                await asyncio.sleep(0.01)

        # Phase 3: Warmup
        async with timer.phase("warmup"):
            async with timer.task("warmup_browser_pool"):
                await asyncio.sleep(0.01)
            async with timer.task("warmup_vector_store"):
                await asyncio.sleep(0.01)

        result = timer.metrics.to_dict()

        # Verify structure
        assert "phases" in result
        assert len(result["phases"]) == 3

        # Verify critical phase
        assert result["phases"]["critical"]["total_ms"] >= 30.0
        assert len(result["phases"]["critical"]["tasks"]) == 3
        assert "init_database" in result["phases"]["critical"]["tasks"]
        assert "migrate_configs" in result["phases"]["critical"]["tasks"]
        assert "ensure_local_admin" in result["phases"]["critical"]["tasks"]

        # Verify core phase
        assert result["phases"]["core"]["total_ms"] >= 20.0
        assert len(result["phases"]["core"]["tasks"]) == 2

        # Verify warmup phase
        assert result["phases"]["warmup"]["total_ms"] >= 20.0
        assert len(result["phases"]["warmup"]["tasks"]) == 2

        # Verify total elapsed
        assert result["total_elapsed_ms"] >= 70.0
