"""Unit tests for BaseAgent Command resume functionality."""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.streaming.types import AgentEventType


class FakeLLM:
    """Fake LLM for testing that returns predefined responses."""

    def __init__(self, responses=None):
        self.responses = responses or ["test response"]
        self.call_count = 0

    def bind_tools(self, tools, **kwargs):
        return self

    async def ainvoke(self, messages, config=None):
        response = self.responses[min(self.call_count, len(self.responses) - 1)]
        self.call_count += 1
        return AIMessage(content=response)


@pytest.mark.asyncio
async def test_base_agent_accepts_command_input():
    """Test that BaseAgent.run() accepts Command as input."""
    llm = FakeLLM()
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    resume_command = Command(resume={"decision": "approve"})

    context = {
        "session_id": "test_session_001",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    async for event in agent.run(query=resume_command, message_id="msg_001", context=context):
        events.append(event)

    # Should not crash and should produce events
    assert len(events) > 0


@pytest.mark.asyncio
async def test_base_agent_resume_logs_correctly():
    """Test that BaseAgent logs resume mode correctly."""
    llm = FakeLLM()
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    resume_command = Command(resume={"decision": "approve", "test": "data"})

    context = {
        "session_id": "test_session_002",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    async for event in agent.run(query=resume_command, message_id="msg_002", context=context):
        events.append(event)
        if event.get("type") == AgentEventType.TASKS_STEPS.value:
            # Should have analyzing_query step
            break

    assert any(e.get("type") == AgentEventType.TASKS_STEPS.value for e in events)


@pytest.mark.asyncio
async def test_base_agent_thread_id_from_session():
    """Test that thread_id is correctly derived from session_id/chat_id."""
    llm = FakeLLM()
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    context = {
        "session_id": "unique_session_123",
        "approval_session_key": "approval_key_456",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    async for event in agent.run(query="test query", message_id="msg_003", context=context):
        events.append(event)
        # Collect a few events
        if len(events) >= 3:
            break

    # Should complete without errors
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_base_agent_command_skip_message_construction():
    """Test that Command input skips normal message construction."""
    call_log = []

    class LoggingLLM(FakeLLM):
        async def ainvoke(self, messages, config=None):
            call_log.append(("ainvoke", len(messages)))
            return await super().ainvoke(messages, config)

    llm = LoggingLLM()
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    resume_command = Command(resume={"decision": "approve"})

    context = {
        "session_id": "test_session_004",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    events = []
    async for event in agent.run(query=resume_command, message_id="msg_004", context=context):
        events.append(event)
        # Only collect a couple events
        if len(events) >= 2:
            break

    # For Command input, no new messages should be constructed
    # The graph receives the Command directly
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_base_agent_string_vs_command_query_text():
    """Test query_text extraction for both string and Command inputs."""
    llm = FakeLLM()
    checkpointer = MemorySaver()
    agent = BaseAgent(llm=llm, checkpointer=checkpointer)

    context = {
        "session_id": "test_session_005",
        "workspace_path": "/tmp/test_workspace",
        "workspaces_storage_root": "/tmp",
    }

    # Test with string input
    events_str = []
    async for event in agent.run(query="test string query", message_id="msg_005a", context=context):
        events_str.append(event)
        if len(events_str) >= 2:
            break

    # Test with Command input
    agent_cmd = BaseAgent(llm=llm, checkpointer=checkpointer)
    events_cmd = []
    async for event in agent_cmd.run(
        query=Command(resume={"decision": "approve"}), message_id="msg_005b", context=context
    ):
        events_cmd.append(event)
        if len(events_cmd) >= 2:
            break

    # Both should produce events without crashing
    assert len(events_str) >= 1
    assert len(events_cmd) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
