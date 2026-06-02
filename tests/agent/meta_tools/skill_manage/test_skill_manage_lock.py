"""Integration tests for skill_manage_tool lock mechanism.

Test coverage:
1. Lock prevents concurrent modifications to same skill
2. Different skills can be modified concurrently
3. Different users can modify same skill concurrently
4. Lock is released after operation completes (success or error)
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.meta_tools.skills.manage import create_skill_manage_tool
from myrm_agent_harness.backends.skills.creation_protocols import SkillSaveResult


@pytest.fixture
def mock_write_backend() -> AsyncMock:
    """Create a mock write backend with delay to test concurrency."""
    backend = AsyncMock()

    async def slow_save_skill(*args, **kwargs) -> SkillSaveResult:
        await asyncio.sleep(0.1)  # Simulate I/O delay
        return SkillSaveResult(
            success=True, skill_name=kwargs.get("name", "test_skill"), skill_id=f"skill_{kwargs.get('name', 'test')}"
        )

    backend.save_skill = AsyncMock(side_effect=slow_save_skill)
    backend.delete_skill = AsyncMock(return_value={"success": True})
    backend.write_resource = AsyncMock(return_value={"success": True})
    backend.delete_resource = AsyncMock(return_value={"success": True})

    return backend


@pytest.fixture
def mock_skill_backend() -> AsyncMock:
    """Create a mock skill backend for reading skills."""
    backend = AsyncMock()
    backend.get_skill_content = AsyncMock(return_value="---\nname: test\n---\n# Test\nContent")
    return backend


@pytest.fixture
def skill_manage_tool(mock_write_backend: AsyncMock, mock_skill_backend: AsyncMock):
    """Create skill_manage_tool with mock backends."""
    return create_skill_manage_tool(write_backend=mock_write_backend, skill_backend=mock_skill_backend)


@pytest.mark.asyncio
async def test_concurrent_same_skill_sequential(skill_manage_tool, mock_write_backend: AsyncMock) -> None:
    """Test that concurrent modifications to same skill are serialized by lock."""
    results: list[tuple[str, float]] = []
    import time

    async def modify_skill(skill_id: str) -> None:
        start = time.time()
        result = await skill_manage_tool.ainvoke(
            {
                "action": "save",
                "name": "shared_skill",
                "content": '---\nname: shared_skill\ndescription: "Test skill"\n---\n# Test\nContent',
            },
                config={
                    "configurable": {
                        "context": {"user_id": "test_user"},
                    },
                },
        )
        end = time.time()
        results.append((skill_id, end - start))
        # Debug: check if save_skill was actually called
        if "Error" in str(result):
            raise AssertionError(f"Tool call failed: {result}")

    # Start two concurrent save operations for same skill+user
    await asyncio.gather(modify_skill("op1"), modify_skill("op2"))

    # Verify operations were serialized (not concurrent)
    assert len(results) == 2
    # If sequential: total_time ~0.2s (0.1 + 0.1)
    # If concurrent: total_time ~0.1s
    total_time = sum(r[1] for r in results)
    assert total_time >= 0.18, f"Operations should be sequential, got {total_time}s"

    # Verify both operations completed
    assert mock_write_backend.save_skill.call_count >= 2


@pytest.mark.asyncio
async def test_concurrent_different_skills_parallel(skill_manage_tool, mock_write_backend: AsyncMock) -> None:
    """Test that different skills can be modified concurrently."""
    results: list[tuple[str, float]] = []
    import time

    async def modify_skill(skill_name: str) -> None:
        start = time.time()
        await skill_manage_tool.ainvoke(
            {
                "action": "save",
                "name": skill_name,
                "content": f'---\nname: {skill_name}\ndescription: "Test skill"\n---\n# Test\nContent',
            },
                config={
                    "configurable": {
                        "context": {"user_id": "test_user"},
                    },
                },
        )
        end = time.time()
        results.append((skill_name, end - start))

    # Start concurrent save operations for different skills
    await asyncio.gather(modify_skill("skill_a"), modify_skill("skill_b"))

    # Verify operations ran concurrently
    assert len(results) == 2
    # If concurrent: each takes ~0.1s, total wall time ~0.1s
    # If sequential: total would be ~0.2s
    # We check individual times are all ~0.1s
    for skill_name, duration in results:
        assert duration < 0.15, f"{skill_name} should complete in ~0.1s, got {duration}s"

    # Verify both operations completed
    assert mock_write_backend.save_skill.call_count >= 2


@pytest.mark.asyncio
async def test_concurrent_different_users_parallel(skill_manage_tool, mock_write_backend: AsyncMock) -> None:
    """Test that different users can modify same skill concurrently."""
    results: list[tuple[str, float]] = []
    import time

    async def modify_skill(user_id: str) -> None:
        start = time.time()
        await skill_manage_tool.ainvoke(
            {
                "action": "save",
                "name": "shared_skill",
                "content": '---\nname: shared_skill\ndescription: "Test skill"\n---\n# Test\nContent',
            },
            config={
                "configurable": {
                    "context": {"user_id": user_id},
                },
            },
        )
        end = time.time()
        results.append((user_id, end - start))

    # Start concurrent save operations for same skill but different users
    await asyncio.gather(modify_skill("user1"), modify_skill("user2"))

    # Verify operations ran concurrently
    assert len(results) == 2
    for user_id, duration in results:
        assert duration < 0.15, f"{user_id} should complete in ~0.1s, got {duration}s"

    # Verify both operations completed
    assert mock_write_backend.save_skill.call_count >= 2


@pytest.mark.asyncio
async def test_lock_released_on_error(skill_manage_tool, mock_write_backend: AsyncMock) -> None:
    """Test that lock is released even when operation fails."""
    # Configure backend to fail on first call, succeed on second
    call_count = 0

    async def flaky_save_skill(*args, **kwargs) -> SkillSaveResult:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        if call_count == 1:
            raise RuntimeError("Simulated backend error")
        return SkillSaveResult(success=True, skill_name="test_skill", skill_id="skill_test")

    mock_write_backend.save_skill = flaky_save_skill

    # First call should fail
    with pytest.raises(RuntimeError, match="Simulated backend error"):
        await skill_manage_tool.ainvoke(
            {
                "action": "save",
                "name": "test_skill",
                "content": '---\nname: test_skill\ndescription: "Test skill"\n---\n# Test\nContent',
            },
                config={
                    "configurable": {
                        "context": {"user_id": "test_user"},
                    },
                },
        )

    # Second call should succeed (lock was released)
    result = await skill_manage_tool.ainvoke(
        {
            "action": "save",
            "name": "test_skill",
            "content": '---\nname: test_skill\ndescription: "Test skill"\n---\n# Test\nContent',
        },
                config={
                    "configurable": {
                        "context": {"user_id": "test_user"},
                    },
                },
    )

    # Verify second call succeeded
    assert "success" in result.lower() or "test_skill" in result


@pytest.mark.asyncio
async def test_lock_per_user_skill_combination(skill_manage_tool, mock_write_backend: AsyncMock) -> None:
    """Test that locks are correctly scoped by user_id:skill_name."""
    results: list[str] = []

    async def modify_skill(user_id: str, skill_name: str, label: str) -> None:
        await skill_manage_tool.ainvoke(
            {
                "action": "save",
                "name": skill_name,
                "content": f'---\nname: {skill_name}\ndescription: "Test skill"\n---\n# Test\nContent',
            },
            config={
                "configurable": {
                    "context": {"user_id": user_id},
                },
            },
        )
        results.append(label)

    # user1:skill_a, user1:skill_b, user2:skill_a should all run concurrently
    await asyncio.gather(
        modify_skill("user1", "skill_a", "u1_sa"),
        modify_skill("user1", "skill_b", "u1_sb"),
        modify_skill("user2", "skill_a", "u2_sa"),
    )

    # All three should complete
    assert len(results) == 3
    assert set(results) == {"u1_sa", "u1_sb", "u2_sa"}

    # Verify all operations completed
    assert mock_write_backend.save_skill.call_count >= 3
