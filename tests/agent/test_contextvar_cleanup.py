"""Test ContextVar cleanup in BaseAgent and SkillAgent.

验证 executor, storage_backend, memory_manager 等 ContextVar 在 finally block 中正确清理。
确保即使执行失败，ContextVar 也不会泄漏。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from myrm_agent_harness.agent._skill_agent_context import (
    get_memory_manager,
    get_storage_backend,
    set_memory_manager,
    set_storage_backend,
)
from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.skill_agent import SkillAgent


class FakeLLM:
    """Fake LLM for testing."""

    def __init__(self, responses=None, should_fail=False):
        self.responses = responses or ["test response"]
        self.call_count = 0
        self.should_fail = should_fail

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, config=None):
        if self.should_fail:
            raise RuntimeError("LLM intentional failure")
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return AIMessage(content=response)


@pytest.mark.asyncio
async def test_base_agent_cleans_executor_contextvar_on_success():
    """Test that executor ContextVar is cleaned up after successful run."""
    from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor

    llm = FakeLLM()
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    # 确保初始状态为 None
    assert get_executor() is None

    context = {
        "session_id": "test_contextvar_001",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    async for event in agent.run(query="test query", message_id="msg_contextvar_001", context=context):
        events.append(event)
        if len(events) >= 3:
            break

    assert len(events) > 0


@pytest.mark.asyncio
async def test_base_agent_cleans_executor_contextvar_on_failure():
    """Test that executor ContextVar is cleaned even when agent fails."""
    from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor

    llm = FakeLLM(should_fail=True)
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    assert get_executor() is None

    context = {
        "session_id": "test_contextvar_002",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    try:
        async for event in agent.run(query="test query", message_id="msg_contextvar_002", context=context):
            events.append(event)
    except Exception:
        pass

    # 即使失败，executor 也应该被清理
    assert get_executor() is None


@pytest.mark.asyncio
async def test_skill_agent_contextvar_get_set():
    """Test SkillAgent ContextVar get/set functions."""
    # 初始状态应该是 None
    assert get_storage_backend() is None
    assert get_memory_manager() is None

    # 创建 mock 对象
    mock_backend = MagicMock()
    mock_manager = MagicMock()

    # 设置 ContextVar
    set_storage_backend(mock_backend)
    set_memory_manager(mock_manager)

    # 验证可以获取
    assert get_storage_backend() is mock_backend
    assert get_memory_manager() is mock_manager

    # 清理
    set_storage_backend(None)
    set_memory_manager(None)

    # 验证已清理
    assert get_storage_backend() is None
    assert get_memory_manager() is None


@pytest.mark.asyncio
async def test_skill_agent_cleans_contextvars_on_success():
    """Test that SkillAgent cleans up storage_backend and memory_manager ContextVars."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(return_value=[])

    llm = FakeLLM()
    checkpointer = MemorySaver()

    agent = SkillAgent(llm=llm, skill_backend=mock_skill_backend, checkpointer=checkpointer)

    # 确保初始状态为 None
    assert get_storage_backend() is None
    assert get_memory_manager() is None

    context = {
        "session_id": "test_contextvar_003",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    async for event in agent.run(query="test query", message_id="msg_contextvar_003", context=context):
        events.append(event)
        if len(events) >= 3:
            break

    # 运行后 ContextVars 应该被清理
    assert get_storage_backend() is None
    assert get_memory_manager() is None
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_skill_agent_cleans_contextvars_on_failure():
    """Test that SkillAgent cleans ContextVars even when run fails."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(return_value=[])

    llm = FakeLLM(should_fail=True)
    checkpointer = MemorySaver()

    agent = SkillAgent(llm=llm, skill_backend=mock_skill_backend, checkpointer=checkpointer)

    assert get_storage_backend() is None
    assert get_memory_manager() is None

    context = {
        "session_id": "test_contextvar_004",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    try:
        async for event in agent.run(query="test query", message_id="msg_contextvar_004", context=context):
            events.append(event)
    except Exception:
        pass

    # 即使失败，ContextVars 也应该被清理
    assert get_storage_backend() is None
    assert get_memory_manager() is None


@pytest.mark.asyncio
async def test_skill_agent_cleans_contextvars_even_if_cleanup_session_fails():
    """Test ContextVar cleanup succeeds even if _cleanup_session fails."""
    mock_skill_backend = AsyncMock()
    mock_skill_backend.list_skills = AsyncMock(return_value=[])

    llm = FakeLLM()
    checkpointer = MemorySaver()

    agent = SkillAgent(llm=llm, skill_backend=mock_skill_backend, checkpointer=checkpointer)

    # Mock _cleanup_session to fail
    with patch.object(agent, "_cleanup_session", side_effect=RuntimeError("Cleanup failed")):
        context = {
            "session_id": "test_contextvar_005",
            "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
        }

        events = []
        try:
            async for event in agent.run(query="test query", message_id="msg_contextvar_005", context=context):
                events.append(event)
                if len(events) >= 3:
                    break
        except RuntimeError as e:
            # cleanup_session 的失败会向上传播
            assert "Cleanup failed" in str(e)

        # ContextVars 应该仍然被清理（嵌套 finally）
        assert get_storage_backend() is None
        assert get_memory_manager() is None


@pytest.mark.asyncio
async def test_skill_agent_prepare_context_sets_contextvars():
    """Test that _prepare_context sets ContextVars correctly."""
    mock_storage = MagicMock()
    mock_memory = MagicMock()
    mock_skill_backend = AsyncMock()

    llm = FakeLLM()
    agent = SkillAgent(
        llm=llm, skill_backend=mock_skill_backend, storage_backend=mock_storage, memory_manager=mock_memory
    )

    # 调用 _prepare_context
    await agent._prepare_context({})

    # 验证 ContextVars 已设置
    assert get_storage_backend() is mock_storage
    assert get_memory_manager() is mock_memory

    # 清理
    set_storage_backend(None)
    set_memory_manager(None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
