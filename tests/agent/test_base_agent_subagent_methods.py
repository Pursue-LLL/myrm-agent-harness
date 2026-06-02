"""Unit tests for BaseAgent subagent management methods.

测试 BaseAgent 的 subagent 管理方法：
1. _spawn_child - 创建子 agent
2. list_children - 列出子 agent
3. cancel_child - 取消子 agent
4. wait_children - 等待多个子 agent
5. 嵌套限制检查
"""

import asyncio

import pytest
from langchain_core.messages import AIMessage

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig


@pytest.fixture(autouse=True)
def setup_configs():
    original = dict(SUBAGENT_CONFIGS)
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS["search"] = SubagentConfig(
        tools=("web_search_tool",),
        system_prompt="Search prompt",
        concurrency_limit=5,
        max_spawn_depth=2,
    )
    SUBAGENT_CONFIGS["browser"] = SubagentConfig(
        tools=("browser_navigate_tool",),
        system_prompt="Browser prompt",
        concurrency_limit=3,
        max_spawn_depth=0,
    )
    yield
    SUBAGENT_CONFIGS.clear()
    SUBAGENT_CONFIGS.update(original)
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus


class FakeLLM:
    """Fake LLM for testing."""

    def __init__(self, response="test response"):
        self.response = response

    def bind(self, **kwargs):
        return self

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, config=None):
        return AIMessage(content=self.response)


def test_base_agent_subagent_views_are_read_only():
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)

    with pytest.raises(TypeError):
        agent._children["task"] = object()

    with pytest.raises(TypeError):
        agent._children_results["task"] = {"success": True}


@pytest.mark.asyncio
async def test_spawn_child_nesting_forbidden():
    """测试嵌套限制检查（browser 不能创建子 agent）"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)

    browser_config = SUBAGENT_CONFIGS["browser"]

    result = await agent._spawn_child(
        task_id="test_id",
        agent_type="browser",
        task_description="test task",
        config=browser_config,
        context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp"},
        tool_registry_getter=lambda: [],
        wait=True,
        parent_type="browser",
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is True


@pytest.mark.asyncio
async def test_spawn_child_nesting_allowed():
    """测试允许嵌套（search 可以创建子 agent）"""
    llm = FakeLLM("子 agent 响应")
    agent = BaseAgent(llm=llm)

    search_config = SUBAGENT_CONFIGS["search"]

    result = await agent._spawn_child(
        task_id="test_id",
        agent_type="search",
        task_description="test search task",
        config=search_config,
        context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp"},
        tool_registry_getter=lambda: [],
        wait=True,
        parent_type="search",
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is True
    assert result.result


@pytest.mark.asyncio
async def test_spawn_child_wait_true():
    """测试 wait=True 同步等待"""
    llm = FakeLLM("子 agent 结果")
    agent = BaseAgent(llm=llm)

    config = SUBAGENT_CONFIGS["search"]

    result = await agent._spawn_child(
        task_id="sync_test",
        agent_type="search",
        task_description="同步任务",
        config=config,
        context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp"},
        tool_registry_getter=lambda: [],
        wait=True,
    )

    assert isinstance(result, SubAgentResult)
    assert result.success is True
    assert result.result
    assert result.task_id == "sync_test"


@pytest.mark.asyncio
async def test_spawn_child_wait_false():
    """测试 wait=False 异步返回"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    config = SUBAGENT_CONFIGS["search"]

    result = await agent._spawn_child(
        task_id="async_test",
        agent_type="search",
        task_description="异步任务",
        config=config,
        context={"session_id": "test_session", "workspace_path": "/tmp/test", "workspaces_storage_root": "/tmp"},
        tool_registry_getter=lambda: [],
        wait=False,
    )

    assert "task_id" in result
    assert result["status"] == "running"

    await asyncio.sleep(0.5)
    assert "async_test" in manager._children_results or "async_test" in manager._children


@pytest.mark.asyncio
async def test_list_children_empty():
    """测试 list_children 空列表"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)

    children = agent.list_children()
    assert children == []


@pytest.mark.asyncio
async def test_list_children_with_running_tasks():
    """测试 list_children 包含运行中的任务"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)

    config = SUBAGENT_CONFIGS["search"]

    await agent._spawn_child(
        task_id="running_task",
        agent_type="search",
        task_description="运行中任务",
        config=config,
        context={"session_id": "test", "workspace_path": "/tmp"},
        tool_registry_getter=lambda: [],
        wait=False,
    )

    children = agent.list_children()
    assert len(children) >= 1
    running = [c for c in children if c["status"] == "running"]
    assert len(running) >= 1


@pytest.mark.asyncio
async def test_cancel_child_success():
    """测试成功取消子 agent"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    async def slow_task():
        await asyncio.sleep(10)
        return {"success": True}

    task_id = "cancel_test"
    manager._children[task_id] = asyncio.create_task(slow_task())

    assert agent.cancel_child(task_id) is True

    await asyncio.sleep(0.1)
    assert manager._children[task_id].cancelled()


@pytest.mark.asyncio
async def test_cancel_child_not_found():
    """测试取消不存在的任务"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)

    assert agent.cancel_child("nonexistent") is False


@pytest.mark.asyncio
async def test_cancel_child_already_done():
    """测试取消已完成的任务"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    async def quick_task():
        return {"success": True}

    task_id = "done_task"
    task = asyncio.create_task(quick_task())
    manager._children[task_id] = task

    await task

    assert agent.cancel_child(task_id) is False


@pytest.mark.asyncio
async def test_wait_children_all_success():
    """测试 wait_children 全部成功"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    async def success_task(task_id: str) -> SubAgentResult:
        await asyncio.sleep(0.1)
        return SubAgentResult(
            success=True,
            result=f"result_{task_id}",
            task_id=task_id,
            agent_type="search",
            status=SubAgentStatus.COMPLETED,
        )

    task_ids = ["task1", "task2", "task3"]
    for tid in task_ids:
        manager._children[tid] = asyncio.create_task(success_task(tid))

    result = await agent.wait_children(task_ids, min_success_rate=1.0)

    assert result["success"] is True
    assert result["success_rate"] == 1.0
    assert len(result["results"]) == 3
    assert len(result["failures"]) == 0


@pytest.mark.asyncio
async def test_wait_children_partial_success():
    """测试 wait_children 部分成功"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    async def success_task() -> SubAgentResult:
        await asyncio.sleep(0.1)
        return SubAgentResult(
            success=True, result="ok", task_id="t", agent_type="search", status=SubAgentStatus.COMPLETED
        )

    async def fail_task() -> SubAgentResult:
        await asyncio.sleep(0.1)
        return SubAgentResult(
            success=False, error="failed", task_id="t", agent_type="search", status=SubAgentStatus.FAILED
        )

    manager._children["task1"] = asyncio.create_task(success_task())
    manager._children["task2"] = asyncio.create_task(fail_task())
    manager._children["task3"] = asyncio.create_task(success_task())

    result = await agent.wait_children(["task1", "task2", "task3"], min_success_rate=0.5)

    assert result["success"] is True
    assert result["success_rate"] >= 0.5
    assert len(result["results"]) == 2
    assert len(result["failures"]) == 1


@pytest.mark.asyncio
async def test_wait_children_below_threshold():
    """测试 wait_children 成功率低于阈值"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    async def fail_task() -> SubAgentResult:
        await asyncio.sleep(0.1)
        return SubAgentResult(
            success=False, error="failed", task_id="t", agent_type="search", status=SubAgentStatus.FAILED
        )

    manager._children["task1"] = asyncio.create_task(fail_task())
    manager._children["task2"] = asyncio.create_task(fail_task())

    result = await agent.wait_children(["task1", "task2"], min_success_rate=0.9)

    assert result["success"] is False
    assert result["success_rate"] == 0.0


@pytest.mark.asyncio
async def test_wait_children_no_tasks():
    """测试 wait_children 空任务列表"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)

    result = await agent.wait_children([], min_success_rate=0.5)

    assert result["success"] is False
    assert len(result["results"]) == 0


@pytest.mark.asyncio
async def test_wait_children_with_exceptions():
    """测试 wait_children 处理异常"""
    llm = FakeLLM()
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    async def exception_task():
        await asyncio.sleep(0.1)
        raise ValueError("Task exception")

    async def success_task() -> SubAgentResult:
        await asyncio.sleep(0.1)
        return SubAgentResult(
            success=True, result="ok", task_id="t", agent_type="search", status=SubAgentStatus.COMPLETED
        )

    manager._children["task1"] = asyncio.create_task(exception_task())
    manager._children["task2"] = asyncio.create_task(success_task())

    result = await agent.wait_children(["task1", "task2"], min_success_rate=0.4)

    assert result["success"] is True
    assert len(result["results"]) + len(result["failures"]) == 2
    assert any(
        "exception" in str(f).lower() or "exception" in str(f.get("error", "")).lower()
        if isinstance(f, dict)
        else False
        for f in result["failures"]
    )


@pytest.mark.asyncio
async def test_children_cleanup_after_completion():
    """测试子 agent 完成后自动清理"""
    llm = FakeLLM("快速响应")
    agent = BaseAgent(llm=llm)
    manager = agent._subagent_manager

    config = SUBAGENT_CONFIGS["search"]

    await agent._spawn_child(
        task_id="cleanup_test",
        agent_type="search",
        task_description="测试清理",
        config=config,
        context={"session_id": "test", "workspace_path": "/tmp"},
        tool_registry_getter=lambda: [],
        wait=True,
    )

    await asyncio.sleep(0.2)

    assert "cleanup_test" not in manager._children
    assert "cleanup_test" in manager._children_results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
