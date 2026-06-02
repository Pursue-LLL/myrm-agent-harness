import asyncio

import pytest

from myrm_agent_harness.agent.skills.evolution.safety.anti_loop_state import InMemoryAntiLoopState


@pytest.fixture
def anti_loop_state():
    return InMemoryAntiLoopState()

@pytest.mark.asyncio
async def test_is_evolution_addressed_initial(anti_loop_state):
    assert not await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill1")

@pytest.mark.asyncio
async def test_mark_and_check(anti_loop_state):
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key1", "skill1")
    assert await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill1")
    assert not await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill2")
    assert not await anti_loop_state.is_evolution_addressed("test_trigger", "key2", "skill1")
    assert not await anti_loop_state.is_evolution_addressed("other_trigger", "key1", "skill1")

@pytest.mark.asyncio
async def test_mark_with_ttl(anti_loop_state):
    # Set a very short TTL
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key1", "skill1", ttl_seconds=0.1)
    assert await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill1")

    # Wait for expiry
    await asyncio.sleep(0.15)

    # Should now be expired and cleared
    assert not await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill1")

    # Verify it was completely cleared from state
    keys = await anti_loop_state.get_all_keys("test_trigger")
    assert "key1" not in keys

@pytest.mark.asyncio
async def test_clear_evolution_state(anti_loop_state):
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key1", "skill1")
    await anti_loop_state.clear_evolution_state("test_trigger", "key1")

    assert not await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill1")

    # Test clearing non-existent state doesn't crash
    await anti_loop_state.clear_evolution_state("test_trigger", "key2")

@pytest.mark.asyncio
async def test_get_all_keys(anti_loop_state):
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key1", "skill1")
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key2", "skill2")

    keys = await anti_loop_state.get_all_keys("test_trigger")
    assert keys == {"key1", "key2"}

    # Different trigger type should have empty keys
    empty_keys = await anti_loop_state.get_all_keys("other_trigger")
    assert empty_keys == set()

@pytest.mark.asyncio
async def test_skill_evolution_attempts(anti_loop_state):
    assert await anti_loop_state.get_skill_evolution_attempts("skill1") == 0

    new_count = await anti_loop_state.increment_skill_evolution_attempts("skill1")
    assert new_count == 1
    assert await anti_loop_state.get_skill_evolution_attempts("skill1") == 1

    new_count = await anti_loop_state.increment_skill_evolution_attempts("skill1")
    assert new_count == 2
    assert await anti_loop_state.get_skill_evolution_attempts("skill1") == 2

@pytest.mark.asyncio
async def test_prune_expired(anti_loop_state):
    # Add one that will expire
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key1", "skill1", ttl_seconds=0.1)
    # Add one that will not expire yet
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key2", "skill2", ttl_seconds=10)
    # Add one without TTL
    await anti_loop_state.mark_evolution_addressed("test_trigger", "key3", "skill3")

    await asyncio.sleep(0.15)

    pruned = await anti_loop_state.prune_expired()
    assert pruned == 1

    # Verify what remains
    assert not await anti_loop_state.is_evolution_addressed("test_trigger", "key1", "skill1")
    assert await anti_loop_state.is_evolution_addressed("test_trigger", "key2", "skill2")
    assert await anti_loop_state.is_evolution_addressed("test_trigger", "key3", "skill3")
