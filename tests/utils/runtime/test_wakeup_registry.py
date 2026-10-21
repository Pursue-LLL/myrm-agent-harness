import pytest

from myrm_agent_harness.agent.sub_agents.types import SubAgentResult
from myrm_agent_harness.utils.runtime.wakeup_registry import (
    AsyncWakeupHandler,
    get_global_wakeup_handler,
    set_global_wakeup_handler,
)


class MockWakeupHandler(AsyncWakeupHandler):
    def __init__(self):
        self.called = False
        self.last_result = None
        self.last_agent_id = None
        self.last_session_id = None

    async def on_async_wakeup(self, result: SubAgentResult, agent_id: str, session_id: str | None) -> None:
        self.called = True
        self.last_result = result
        self.last_agent_id = agent_id
        self.last_session_id = session_id


@pytest.fixture(autouse=True)
def reset_registry():
    """Ensure the registry is clean before and after each test."""
    set_global_wakeup_handler(None)
    yield
    set_global_wakeup_handler(None)


def test_set_and_get_global_wakeup_handler():
    """Test that the global wakeup handler can be set and retrieved."""
    assert get_global_wakeup_handler() is None

    handler = MockWakeupHandler()
    set_global_wakeup_handler(handler)

    assert get_global_wakeup_handler() is handler

    set_global_wakeup_handler(None)
    assert get_global_wakeup_handler() is None


@pytest.mark.asyncio
async def test_handler_protocol():
    """Test that the handler correctly implements the protocol and can be called."""
    handler = MockWakeupHandler()
    set_global_wakeup_handler(handler)

    retrieved = get_global_wakeup_handler()
    assert retrieved is not None

    mock_result = SubAgentResult(
        task_id="task-123",
        agent_type="test_agent",
        success=True,
    )

    await retrieved.on_async_wakeup(mock_result, "parent-agent", "session-456")

    assert handler.called
    assert handler.last_result == mock_result
    assert handler.last_agent_id == "parent-agent"
    assert handler.last_session_id == "session-456"
