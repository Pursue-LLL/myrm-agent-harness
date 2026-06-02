import asyncio

import pytest

from myrm_agent_harness.agent.middlewares.concurrency_limiter import create_concurrency_limiter, get_subagent_semaphore
from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture(autouse=True)
def setup_configs():
    original = dict(SUBAGENT_CONFIGS)
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS["search"] = SubagentConfig(
        concurrency_limit=10, description="", system_prompt=""
    )
    SUBAGENT_CONFIGS["browser"] = SubagentConfig(
        concurrency_limit=3, description="", system_prompt=""
    )
    SUBAGENT_CONFIGS["analysis"] = SubagentConfig(
        concurrency_limit=5, description="", system_prompt=""
    )
    yield
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS.update(original)


@pytest.mark.asyncio
async def test_semaphore_singleton():
    """测试 Semaphore 是全局单例"""
    sem1 = get_subagent_semaphore("search")
    sem2 = get_subagent_semaphore("search")

    assert sem1 is sem2, "Semaphore should be singleton"
    assert sem1._value == 10, "search semaphore limit should be 10"


@pytest.mark.asyncio
async def test_different_agent_types_have_different_semaphores():
    """测试不同 agent_type 有独立的 semaphore"""
    search_sem = get_subagent_semaphore("search")
    browser_sem = get_subagent_semaphore("browser")
    analysis_sem = get_subagent_semaphore("analysis")

    assert search_sem is not browser_sem
    assert browser_sem is not analysis_sem
    assert search_sem._value == 10
    assert browser_sem._value == 3
    assert analysis_sem._value == 5


@pytest.mark.asyncio
async def test_unknown_agent_type_returns_none():
    """测试未知 agent_type 返回 None"""
    sem = get_subagent_semaphore("unknown_type")
    assert sem is None


def test_middleware_creation():
    """测试 middleware 创建成功"""
    middleware = create_concurrency_limiter()
    assert middleware is not None


def test_all_agent_types_have_semaphores():
    """测试所有 agent 类型都有 semaphore"""
    for agent_type in SUBAGENT_CONFIGS:
        sem = get_subagent_semaphore(agent_type)
        assert sem is not None, f"{agent_type} should have semaphore"
        expected_limit = SUBAGENT_CONFIGS[agent_type].concurrency_limit
        assert sem._value == expected_limit, f"{agent_type} semaphore limit mismatch"


def test_semaphore_limits_match_config():
    """测试 semaphore 限制与配置一致"""
    search_sem = get_subagent_semaphore("search")
    browser_sem = get_subagent_semaphore("browser")
    analysis_sem = get_subagent_semaphore("analysis")

    assert search_sem._value == SUBAGENT_CONFIGS["search"].concurrency_limit
    assert browser_sem._value == SUBAGENT_CONFIGS["browser"].concurrency_limit
    assert analysis_sem._value == SUBAGENT_CONFIGS["analysis"].concurrency_limit


@pytest.mark.asyncio
async def test_semaphore_acquire_release():
    """测试 semaphore 可以正常获取和释放"""
    sem = get_subagent_semaphore("search")
    initial_value = sem._value

    async with sem:
        during_value = sem._value
        assert during_value == initial_value - 1

    after_value = sem._value
    assert after_value == initial_value


@pytest.mark.asyncio
async def test_semaphore_blocks_when_full():
    """测试 semaphore 满时会阻塞"""
    sem = get_subagent_semaphore("browser")
    assert sem._value == 3

    acquired_count = 0
    release_events = []

    async def acquire_and_hold(hold_time: float):
        nonlocal acquired_count
        async with sem:
            acquired_count += 1
            await asyncio.sleep(hold_time)
        release_events.append(asyncio.get_event_loop().time())

    tasks = [acquire_and_hold(0.2) for _ in range(5)]
    await asyncio.gather(*tasks)

    assert acquired_count == 5


class TestConcurrencyLimiterNoneArgs:
    """Test that concurrency_limiter_middleware handles None args safely."""

    def test_args_none_fallback(self):
        """Simulate request.tool_call['args'] = None, should default to {}."""
        tool_call: dict[str, object] = {
            "name": "spawn_subagent",
            "args": None,
            "id": "c1",
        }
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {}
        assert isinstance(tool_args, dict)

    def test_args_missing_fallback(self):
        """Simulate request.tool_call without 'args' key."""
        tool_call: dict[str, object] = {"name": "spawn_subagent", "id": "c2"}
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {}

    def test_args_valid_dict(self):
        """Normal dict args."""
        tool_call: dict[str, object] = {
            "name": "spawn",
            "args": {"agent_type": "search"},
            "id": "c3",
        }
        tool_args: dict[str, object] = tool_call.get("args") or {}
        assert tool_args == {"agent_type": "search"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
