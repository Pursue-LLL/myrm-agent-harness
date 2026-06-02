"""Tests for StreamingAggregator snapshot persistence"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from myrm_agent_harness.agent.skills.optimization import StreamingAggregator
from myrm_agent_harness.agent.skills.optimization.event_emitter import EventEmitter
from myrm_agent_harness.agent.skills.optimization.in_memory_storage import InMemoryStorage
from myrm_agent_harness.agent.skills.optimization.types import SkillQualityScore


@pytest_asyncio.fixture
async def in_memory_storage():
    """In-memory storage for testing"""
    return InMemoryStorage()


@pytest_asyncio.fixture
async def event_emitter():
    """Event emitter"""
    return EventEmitter()


def create_test_score() -> SkillQualityScore:
    """Helper to create test SkillQualityScore"""
    return SkillQualityScore(
        success_rate=0.9, token_efficiency=0.8, execution_time=0.8, user_satisfaction=0.9, call_frequency=0.7
    )


@pytest.mark.asyncio
async def test_snapshot_save_and_load(in_memory_storage, event_emitter):
    """Test snapshot save and load functionality"""
    aggregator = StreamingAggregator(
        storage=in_memory_storage, event_emitter=event_emitter, enable_snapshot=True, snapshot_interval_seconds=999999
    )

    score = create_test_score()

    await event_emitter.emit("skill_executed", {"skill_id": "test-skill", "quality_score": score})

    aggregates_before = await aggregator.aggregate_by_skill("test-skill")
    assert len(aggregates_before) == 1
    assert aggregates_before[0].sample_count == 1

    await aggregator.save_snapshot()

    new_aggregator = StreamingAggregator(
        storage=in_memory_storage, event_emitter=event_emitter, enable_snapshot=True, snapshot_interval_seconds=999999
    )

    await asyncio.sleep(0.3)

    aggregates_after = await new_aggregator.aggregate_by_skill("test-skill")
    assert len(aggregates_after) == 1
    assert aggregates_after[0].sample_count == 1


@pytest.mark.asyncio
async def test_snapshot_disabled(in_memory_storage, event_emitter):
    """Test that snapshot is disabled when enable_snapshot=False"""
    aggregator = StreamingAggregator(storage=in_memory_storage, event_emitter=event_emitter, enable_snapshot=False)

    score = create_test_score()

    await event_emitter.emit("skill_executed", {"skill_id": "test-skill", "quality_score": score})

    await aggregator.save_snapshot()

    new_aggregator = StreamingAggregator(storage=in_memory_storage, event_emitter=event_emitter, enable_snapshot=False)

    await asyncio.sleep(0.3)

    aggregates = await new_aggregator.aggregate_by_skill("test-skill")
    assert len(aggregates) == 0
