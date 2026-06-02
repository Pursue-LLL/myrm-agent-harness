import asyncio
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionProposal, EvolutionRequest, EvolutionType
from myrm_agent_harness.agent.skills.evolution.infra.queue import EvolutionQueue, QueuePriority, get_evolution_queue


@pytest.fixture
def sample_request():
    return EvolutionRequest(
        agent_id="agent1",
        tool_call_ids=["call1"],
        skill_id="skill1",
        evolution_type=EvolutionType.FIX,
        reason="test"
    )

@pytest.mark.asyncio
async def test_queue_enqueue(sample_request):
    queue = EvolutionQueue()
    res = await queue.enqueue(sample_request, priority=QueuePriority.HIGH)
    assert res is True
    assert queue._queues[QueuePriority.HIGH].qsize() == 1

@pytest.mark.asyncio
async def test_queue_enqueue_full_drops_oldest(sample_request):
    queue = EvolutionQueue(max_queue_size=4) # max // 4 == 1
    await queue.enqueue(sample_request, priority=QueuePriority.NORMAL)
    assert queue._queues[QueuePriority.NORMAL].qsize() == 1

    # Next enqueue should drop the oldest one (which is sample_request)
    req2 = EvolutionRequest(
        agent_id="agent2",
        tool_call_ids=["call2"],
        skill_id="skill2",
        evolution_type=EvolutionType.OPTIMIZE_DESCRIPTION,
        reason=""
    )
    await queue.enqueue(req2, priority=QueuePriority.NORMAL)
    assert queue._queues[QueuePriority.NORMAL].qsize() == 1

    # Verify the remaining item is req2
    item = queue._queues[QueuePriority.NORMAL].get_nowait()
    assert item.request.skill_id == "skill2"

@pytest.mark.asyncio
async def test_queue_start_stop():
    queue = EvolutionQueue(worker_count=1)
    await queue.start()
    assert queue._running is True
    assert len(queue._workers) == 1

    # Starting again should be a no-op warning
    await queue.start()
    assert len(queue._workers) == 1

    await queue.stop()
    assert queue._running is False
    assert len(queue._workers) == 0

@pytest.mark.asyncio
async def test_worker_process_evolution(sample_request):
    queue = EvolutionQueue(worker_count=1)

    mock_handler = AsyncMock(return_value=EvolutionProposal(
        agent_id="agent1",
        skill_id="skill1",
        proposed_content="pass",
        original_content="pass_old",
        diff="--- a\n+++ b",
        score=0.9,
        evolution_type=EvolutionType.FIX,
        reasoning="fix"
    ))
    queue.set_evolution_handler(mock_handler)

    await queue.enqueue(sample_request)

    # Start worker, wait a bit, stop worker
    await queue.start()
    await asyncio.sleep(0.1)
    await queue.stop()

    mock_handler.assert_called_once_with(sample_request)
    assert queue._processed_count == 1

@pytest.mark.asyncio
async def test_worker_process_evolution_error_retry(sample_request):
    queue = EvolutionQueue(worker_count=1)

    mock_handler = AsyncMock(side_effect=Exception("Test error"))
    queue.set_evolution_handler(mock_handler)

    await queue.enqueue(sample_request)

    # Start worker
    await queue.start()
    # It should retry. Wait enough time for a retry. (Wait a bit longer since there is a fallback sleep on error? Wait, the queue puts it back)
    await asyncio.sleep(0.2)
    await queue.stop()

    assert mock_handler.call_count > 0
    # Wait, error tracking might have increased
    assert queue._failed_count >= 1

def test_get_evolution_queue():
    q1 = get_evolution_queue()
    q2 = get_evolution_queue()
    assert q1 is q2
