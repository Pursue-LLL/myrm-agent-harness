import asyncio
import contextlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.optimization.config import MonitoringConfig, OptimizationConfig
from myrm_agent_harness.agent.skills.optimization.scheduler import OptimizationScheduler
from myrm_agent_harness.agent.skills.optimization.types import SkillQualityScore
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def mock_optimizer():
    optimizer = AsyncMock()
    optimizer.optimize_skill.return_value = MagicMock(success=True, duration_seconds=1.0, version=2)
    return optimizer


@pytest.fixture
def mock_event_emitter():
    emitter = AsyncMock()
    return emitter


@pytest.fixture
def scheduler(mock_optimizer, mock_event_emitter):
    config = OptimizationConfig(
        monitoring=MonitoringConfig(circuit_breaker_threshold=5, evaluation_interval=0.1, cooldown_period=3600)
    )
    sched = OptimizationScheduler(
        optimizer=mock_optimizer,
        execution_provider=AsyncMock(),
        quality_calculator=MagicMock(),
        config=config,
        event_emitter=mock_event_emitter,
        anomaly_detector=MagicMock(),
    )
    return sched


@pytest.mark.asyncio
async def test_trigger_batch_optimization(scheduler):
    skill_ids = ["skill_1", "skill_2", "skill_3"]

    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    scheduler.execution_provider.get_skill_metadata = AsyncMock(return_value=metadata)
    mock_sample = MagicMock()
    mock_sample.skill = metadata
    scheduler.execution_provider.get_skill_executions = AsyncMock(return_value=[mock_sample])
    scheduler.quality_calculator.calculate = AsyncMock(return_value=quality)

    batch_id = await scheduler.trigger_batch_optimization(skill_ids, max_concurrent=2)

    assert batch_id is not None
    assert batch_id in scheduler._batch_tasks

    batch_info = scheduler.get_batch_status(batch_id)
    assert batch_info["total"] == 3
    assert batch_info["completed"] == 0
    assert batch_info["status"] == "running"

    await asyncio.sleep(0.1)

    assert scheduler.optimizer.optimize_skill.call_count == 3


@pytest.mark.asyncio
async def test_queue_worker(scheduler):
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    await scheduler._optimization_queue.put((metadata, quality))

    worker_task = asyncio.create_task(scheduler._queue_worker())

    await asyncio.sleep(0.1)

    worker_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker_task

    scheduler.optimizer.optimize_skill.assert_called_once()
    assert scheduler._metrics["optimization_total"] == 1
    assert scheduler._metrics["optimization_success"] == 1


@pytest.mark.asyncio
async def test_reload_config(scheduler):
    new_config = OptimizationConfig(monitoring=MonitoringConfig(circuit_breaker_threshold=10))

    await scheduler.reload_config(new_config)

    assert scheduler.config.monitoring.circuit_breaker_threshold == 10
    scheduler.event_emitter.emit.assert_called_with(
        "config_reloaded",
        {
            "old_config": {
                "optimization_threshold": 0.6,
                "cooldown_period": 3600,
                "circuit_breaker_threshold": 5,
            },
            "new_config": {
                "optimization_threshold": 0.6,
                "cooldown_period": 86400.0,
                "circuit_breaker_threshold": 10,
            },
        },
    )


def test_get_metrics(scheduler):
    scheduler._metrics["optimization_total"] = 10
    scheduler._metrics["optimization_success"] = 8
    scheduler._metrics["optimization_failed"] = 2
    scheduler._metrics["total_duration"] = 20.0

    metrics = scheduler.get_metrics()

    assert metrics["optimization_success"] == 8
    assert metrics["optimization_failed"] == 2
    assert metrics["optimization_success_rate"] == 0.8
    assert "queue_size" in metrics


@pytest.mark.asyncio
async def test_health_check(scheduler):
    scheduler._running = True

    health = await scheduler.health_check()

    assert health["healthy"] is True
    assert health["component"] == "optimization_scheduler"
    assert health["queue_worker_active"] is False


@pytest.mark.asyncio
async def test_trigger_optimization(scheduler):
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    scheduler.execution_provider.get_skill_metadata = AsyncMock(return_value=metadata)
    mock_sample = MagicMock()
    mock_sample.skill = metadata
    scheduler.execution_provider.get_skill_executions = AsyncMock(return_value=[mock_sample])
    scheduler.quality_calculator.calculate = AsyncMock(return_value=quality)

    # Should trigger
    triggered = await scheduler.trigger_optimization(metadata, quality)
    assert triggered is True
    assert scheduler._optimization_queue.qsize() == 1

    # Record success to set cooldown
    scheduler._record_success("skill_1")

    # Should not trigger again (cooldown)
    triggered = await scheduler.trigger_optimization(metadata, quality)
    assert triggered is False
    assert scheduler._optimization_queue.qsize() == 1


def test_circuit_breaker(scheduler):
    assert scheduler._is_circuit_broken("skill_1") is False

    for _ in range(5):
        scheduler._record_failure("skill_1", "error")

    assert scheduler._is_circuit_broken("skill_1") is True

    scheduler._record_success("skill_1")
    assert scheduler._is_circuit_broken("skill_1") is False


@pytest.mark.asyncio
async def test_dlq_operations(scheduler):
    # Add to DLQ
    scheduler._dead_letter_queue.append(
        {"task_id": "task_1", "skill_id": "skill_1", "error": "Timeout", "timestamp": datetime.now()}
    )

    tasks = scheduler.get_dlq_tasks()
    assert len(tasks) == 1
    assert tasks[0]["task_id"] == "task_1"

    # Retry task
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    scheduler.execution_provider.get_skill_metadata = AsyncMock(return_value=metadata)
    mock_sample = MagicMock()
    mock_sample.skill = metadata
    scheduler.execution_provider.get_skill_executions = AsyncMock(return_value=[mock_sample])
    scheduler.quality_calculator.calculate = AsyncMock(return_value=quality)

    success = await scheduler.retry_dlq_task("task_1")
    assert success is True
    assert len(scheduler._dead_letter_queue) == 0
    assert scheduler._optimization_queue.qsize() == 1

    # Retry task error
    scheduler._dead_letter_queue.append(
        {"task_id": "task_error", "skill_id": "skill_error", "error": "Timeout", "timestamp": datetime.now()}
    )
    scheduler.execution_provider.get_skill_executions.side_effect = Exception("DB error")
    success = await scheduler.retry_dlq_task("task_error")
    assert success is False
    assert len(scheduler._dead_letter_queue) == 1

    # Clear DLQ
    scheduler._dead_letter_queue.append({"task_id": "task_2"})
    cleared = scheduler.clear_dlq()
    assert cleared == 2
    assert len(scheduler._dead_letter_queue) == 0


@pytest.mark.asyncio
async def test_monitoring_loop(scheduler):
    # Mock evaluate_all_skills
    scheduler._evaluate_all_skills = AsyncMock()

    # Start monitoring
    await scheduler.start_monitoring()

    # Wait for loop
    await asyncio.sleep(0.2)

    # Stop monitoring
    await scheduler.stop_monitoring()

    assert scheduler._evaluate_all_skills.call_count >= 1


@pytest.mark.asyncio
async def test_evaluate_all_skills(scheduler):
    scheduler.execution_provider.get_all_skill_ids = AsyncMock(return_value=["skill_1"])
    scheduler._evaluate_skill = AsyncMock()
    scheduler._detect_and_handle_anomalies = AsyncMock()

    await scheduler._evaluate_all_skills()

    scheduler._evaluate_skill.assert_called_once_with("skill_1")
    scheduler._detect_and_handle_anomalies.assert_called_once()


@pytest.mark.asyncio
async def test_evaluate_skill(scheduler):
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    scheduler.execution_provider.get_skill_metadata = AsyncMock(return_value=metadata)
    mock_sample = MagicMock()
    mock_sample.skill = metadata
    scheduler.execution_provider.get_skill_executions = AsyncMock(return_value=[mock_sample])
    scheduler.quality_calculator.calculate = AsyncMock(return_value=quality)

    await scheduler._evaluate_skill("skill_1")

    assert scheduler._optimization_queue.qsize() == 1


@pytest.mark.asyncio
async def test_detect_and_handle_anomalies(scheduler):
    scheduler.anomaly_detector = MagicMock()
    mock_anomaly = MagicMock()
    mock_anomaly.skill_id = "skill_1"
    mock_anomaly.z_score = 3.5
    mock_anomaly.quality_score = 0.4
    mock_anomaly.timestamp = datetime.now()
    mock_anomaly.root_cause.cause_type = "high_failure_rate"

    scheduler.anomaly_detector.detect_quality_anomalies = AsyncMock(return_value=[mock_anomaly])

    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    scheduler.execution_provider.get_skill_metadata = AsyncMock(return_value=metadata)
    mock_sample = MagicMock()
    mock_sample.skill = metadata
    scheduler.execution_provider.get_skill_executions = AsyncMock(return_value=[mock_sample])
    scheduler.quality_calculator.calculate = AsyncMock(return_value=quality)

    await scheduler._detect_and_handle_anomalies()

    assert scheduler._optimization_queue.qsize() == 1


@pytest.mark.asyncio
async def test_start_stop_queue_worker(scheduler):
    await scheduler.start_queue_worker()
    assert scheduler._queue_worker_task is not None
    assert not scheduler._queue_worker_task.done()

    await scheduler.stop_queue_worker()
    assert scheduler._queue_worker_task.done()


@pytest.mark.asyncio
async def test_register_hooks(scheduler):
    mock_registry = MagicMock()
    scheduler._register_hooks(mock_registry)
    mock_registry.register.assert_called_once()

    # Extract the hook callback
    hook_def = mock_registry.register.call_args[0][1]

    # Test the callback
    callback = hook_def.fn

    # Should skip if not running
    scheduler._running = False
    await callback("test", {})

    # Should process if running
    scheduler._running = True
    result = await callback("test", {"tool_name": "skill_1"})
    assert result.success is True


@pytest.mark.asyncio
async def test_execute_optimization_error(scheduler):
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5, token_efficiency=0.5, execution_time=0.5, user_satisfaction=0.5, call_frequency=0.5
    )

    scheduler.optimizer.optimize_skill.side_effect = Exception("Optimization failed")

    with pytest.raises(Exception, match="Optimization failed"):
        await scheduler._execute_optimization(metadata, quality)

    assert scheduler._metrics["optimization_failed"] == 1
    assert scheduler._is_circuit_broken("skill_1") is False

    # Check circuit breaker
    for _ in range(4):
        with pytest.raises(Exception):
            await scheduler._execute_optimization(metadata, quality)

    assert scheduler._is_circuit_broken("skill_1") is True

    # Check DLQ
    assert len(scheduler._dead_letter_queue) == 1
