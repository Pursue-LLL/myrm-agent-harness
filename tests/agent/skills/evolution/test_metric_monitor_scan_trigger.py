"""MetricMonitor scans once per ``scan_interval`` counted skill executions.

With no executions the monitor stays idle: the background poll must not rescan
the store every few seconds.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.infra import monitor as monitor_module
from myrm_agent_harness.agent.skills.evolution.infra.monitor import MetricMonitor

_INTERVAL = 3
_REAL_SLEEP = asyncio.sleep


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SkillStore]:
    skill_store = SkillStore(db_path=tmp_path / "skills.db")
    yield skill_store
    skill_store.close()


@pytest.fixture
def monitor(store: SkillStore) -> MetricMonitor:
    return MetricMonitor(store=store, engine=MagicMock(), scan_interval=_INTERVAL, enable_llm_confirmation=False)


@pytest.fixture
async def fast_poll(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Shrink the scheduler's 5s poll so the loop can be observed within a test."""

    async def short_sleep(_delay: float) -> None:
        await _REAL_SLEEP(0.01)

    monkeypatch.setattr(monitor_module.asyncio, "sleep", short_sleep)
    yield


def test_idle_monitor_does_not_ask_for_a_scan(monitor: MetricMonitor) -> None:
    assert monitor.should_scan() is False


def test_scan_is_due_after_one_interval_of_executions(monitor: MetricMonitor) -> None:
    for _ in range(_INTERVAL - 1):
        monitor.increment_execution_count()
    assert monitor.should_scan() is False

    monitor.increment_execution_count()
    assert monitor.should_scan() is True


@pytest.mark.asyncio
async def test_a_scan_resets_the_interval(monitor: MetricMonitor) -> None:
    for _ in range(_INTERVAL):
        monitor.increment_execution_count()

    await monitor.scan_and_evolve()
    assert monitor.should_scan() is False

    for _ in range(_INTERVAL):
        monitor.increment_execution_count()
    assert monitor.should_scan() is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("fast_poll")
async def test_background_loop_scans_once_per_interval_not_per_poll(monitor: MetricMonitor) -> None:
    await monitor.start()
    try:
        await _REAL_SLEEP(0.2)
        assert monitor.get_stats()["total_scans"] == 0

        for _ in range(_INTERVAL):
            monitor.increment_execution_count()
        await _REAL_SLEEP(0.2)
        assert monitor.get_stats()["total_scans"] == 1
    finally:
        await monitor.stop()
