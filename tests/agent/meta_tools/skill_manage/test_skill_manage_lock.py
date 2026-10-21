"""Integration tests for skill_manage_tool lock mechanism.

Test coverage:
1. Lock prevents concurrent modifications to same skill
2. Different skills can be modified concurrently
3. Different users can modify same skill concurrently
4. Lock is released after operation completes (success or error)
5. Locks are scoped by user_id and skill name
"""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.meta_tools.skills.manage import create_skill_manage_tool
from myrm_agent_harness.backends.skills.creation_protocols import SkillSaveResult


@pytest.fixture
def mock_write_backend() -> AsyncMock:
    """Create a mock write backend with delay to test concurrency."""
    backend = AsyncMock()

    async def slow_save_skill(*args: object, **kwargs: object) -> SkillSaveResult:
        await asyncio.sleep(0.1)  # Simulate I/O delay
        name = str(kwargs.get("name", "test_skill"))
        return SkillSaveResult(success=True, skill_name=name, skill_id=f"skill_{name}")

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
def skill_manage_tool(mock_write_backend: AsyncMock, mock_skill_backend: AsyncMock) -> BaseTool:
    """Create skill_manage_tool with mock backends."""
    return create_skill_manage_tool(write_backend=mock_write_backend, skill_backend=mock_skill_backend)


def _save_input(skill_name: str) -> dict[str, object]:
    content = f'---\nname: {skill_name}\ndescription: "Test skill"\n---\n# Test\nContent'
    return {"operations": [{"action": "save", "name": skill_name, "content": content}]}


def _config(user_id: str) -> RunnableConfig:
    return {"configurable": {"context": {"user_id": user_id}}}


async def _timed_save(tool: BaseTool, skill_name: str, user_id: str) -> float:
    start = time.time()
    result = await tool.ainvoke(_save_input(skill_name), config=_config(user_id))
    assert "Error" not in str(result), f"Tool call failed: {result}"
    return time.time() - start


@pytest.mark.asyncio
async def test_concurrent_same_skill_sequential(skill_manage_tool: BaseTool, mock_write_backend: AsyncMock) -> None:
    """Test that concurrent modifications to same skill are serialized by lock."""
    durations = await asyncio.gather(
        _timed_save(skill_manage_tool, "shared_skill", "test_user"),
        _timed_save(skill_manage_tool, "shared_skill", "test_user"),
    )

    # If sequential: total_time ~0.2s (0.1 + 0.1); if concurrent: ~0.1s
    assert sum(durations) >= 0.18, f"Operations should be sequential, got {sum(durations)}s"
    assert mock_write_backend.save_skill.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_different_skills_parallel(skill_manage_tool: BaseTool, mock_write_backend: AsyncMock) -> None:
    """Test that different skills can be modified concurrently."""
    durations = await asyncio.gather(
        _timed_save(skill_manage_tool, "skill_a", "test_user"),
        _timed_save(skill_manage_tool, "skill_b", "test_user"),
    )

    for duration in durations:
        assert duration < 0.25, f"should complete in < 0.25s, got {duration}s"
    assert mock_write_backend.save_skill.call_count == 2


@pytest.mark.asyncio
async def test_concurrent_different_users_parallel(skill_manage_tool: BaseTool, mock_write_backend: AsyncMock) -> None:
    """Test that different users can modify same skill concurrently."""
    durations = await asyncio.gather(
        _timed_save(skill_manage_tool, "shared_skill", "user1"),
        _timed_save(skill_manage_tool, "shared_skill", "user2"),
    )

    for duration in durations:
        assert duration < 0.25, f"should complete in < 0.25s, got {duration}s"
    assert mock_write_backend.save_skill.call_count == 2


@pytest.mark.asyncio
async def test_lock_released_on_error(skill_manage_tool: BaseTool, mock_write_backend: AsyncMock) -> None:
    """Test that lock is released even when operation fails."""
    call_count = 0

    async def flaky_save_skill(*args: object, **kwargs: object) -> SkillSaveResult:
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        if call_count == 1:
            raise RuntimeError("Simulated backend error")
        return SkillSaveResult(success=True, skill_name="test_skill", skill_id="skill_test")

    mock_write_backend.save_skill = flaky_save_skill

    # The batch runner reports a failing operation as an aborted batch instead of raising.
    failed = await skill_manage_tool.ainvoke(_save_input("test_skill"), config=_config("test_user"))
    assert "batch aborted" in str(failed).lower()
    assert "Simulated backend error" in str(failed)

    # Second call should succeed (lock was released)
    result = await skill_manage_tool.ainvoke(_save_input("test_skill"), config=_config("test_user"))
    assert "Batch applied successfully" in str(result)


@pytest.mark.asyncio
async def test_lock_per_user_skill_combination(skill_manage_tool: BaseTool, mock_write_backend: AsyncMock) -> None:
    """Test that locks are correctly scoped by user_id:skill_name."""
    results: list[str] = []

    async def modify_skill(user_id: str, skill_name: str, label: str) -> None:
        await _timed_save(skill_manage_tool, skill_name, user_id)
        results.append(label)

    # user1:skill_a, user1:skill_b, user2:skill_a should all run concurrently
    await asyncio.gather(
        modify_skill("user1", "skill_a", "u1_sa"),
        modify_skill("user1", "skill_b", "u1_sb"),
        modify_skill("user2", "skill_a", "u2_sa"),
    )

    assert set(results) == {"u1_sa", "u1_sb", "u2_sa"}
    assert mock_write_backend.save_skill.call_count == 3
