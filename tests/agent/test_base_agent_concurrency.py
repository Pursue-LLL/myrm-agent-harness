import asyncio

import pytest
from langchain_core.language_models import FakeListChatModel

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.errors.agent_errors import AgentBusyError


@pytest.mark.asyncio
async def test_agent_busy_error_raised():
    llm = FakeListChatModel(responses=["mock response"])
    agent = BaseAgent(llm=llm)

    # Mock _run_internal to simulate a long-running task
    async def mock_run_internal(*args, **kwargs):
        await asyncio.sleep(0.5)
        yield {"type": "mock_event"}

    agent._run_internal = mock_run_internal

    # Start the first run
    async def run_agent():
        events = []
        async for e in agent.run("test1"):
            events.append(e)
        return events

    task1 = asyncio.create_task(run_agent())

    # Wait a tiny bit to ensure task1 sets _is_running
    await asyncio.sleep(0.1)

    # Attempt to start a second run concurrently
    with pytest.raises(AgentBusyError, match="Agent is already running"):
        async for _ in agent.run("test2"):
            pass

    # Wait for task1 to finish
    await task1

    # Verify _is_running is reset
    assert agent._is_running is False


@pytest.mark.asyncio
async def test_is_running_reset_on_success():
    llm = FakeListChatModel(responses=["mock response"])
    agent = BaseAgent(llm=llm)

    async def mock_run_internal(*args, **kwargs):
        yield {"type": "mock_event"}

    agent._run_internal = mock_run_internal

    async for _ in agent.run("test"):
        assert agent._is_running is True

    assert agent._is_running is False


@pytest.mark.asyncio
async def test_is_running_reset_on_error():
    llm = FakeListChatModel(responses=["mock response"])
    agent = BaseAgent(llm=llm)

    async def mock_run_internal(*args, **kwargs):
        raise ValueError("Simulated error")
        yield {"type": "mock_event"}

    agent._run_internal = mock_run_internal

    with pytest.raises(ValueError, match="Simulated error"):
        async for _ in agent.run("test"):
            pass

    assert agent._is_running is False
