from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.skills.evolution.pipeline.trace_analyzer import TraceAnalyzer


class DummyEvent:
    def __init__(self, event_type, data):
        self.event_type = event_type
        self.data = data

@pytest.fixture
def mock_backend():
    return AsyncMock(spec=EventLogBackend)

@pytest.mark.asyncio
async def test_analyze_slice_no_backend():
    analyzer = TraceAnalyzer(backend=None)
    result = await analyzer.analyze_slice("session_1", ["call_1"])
    assert result is None

@pytest.mark.asyncio
async def test_analyze_slice_no_tool_call_ids(mock_backend):
    analyzer = TraceAnalyzer(backend=mock_backend)
    result = await analyzer.analyze_slice("session_1", [])
    assert result is None

@pytest.mark.asyncio
async def test_analyze_slice_no_events(mock_backend):
    mock_backend.get_events.return_value = []
    analyzer = TraceAnalyzer(backend=mock_backend)
    result = await analyzer.analyze_slice("session_1", ["call_1"])
    assert result is None

@pytest.mark.asyncio
async def test_analyze_slice_no_matching_events(mock_backend):
    event = DummyEvent(event_type="test", data={"tool_call_id": "other_call"})
    mock_backend.get_events.return_value = [event]

    analyzer = TraceAnalyzer(backend=mock_backend)
    result = await analyzer.analyze_slice("session_1", ["call_1"])
    assert result is None

@pytest.mark.asyncio
async def test_analyze_slice_success(mock_backend):
    event1 = DummyEvent(event_type="pre_tool_use", data={"tool_call_id": "call_1", "tool_name": "test_tool", "tool_input": {"args": 1}})

    event2 = DummyEvent(event_type="post_tool_use", data={"tool_call_id": "call_1", "tool_output": "success result"})

    mock_backend.get_events.return_value = [event1, event2]

    analyzer = TraceAnalyzer(backend=mock_backend)
    result = await analyzer.analyze_slice("session_1", ["call_1"])

    assert result is not None
    assert result.is_coherent is True
    assert "test_tool" in result.formatted_trace
    assert "success result" in result.formatted_trace

@pytest.mark.asyncio
async def test_analyze_slice_failure_incoherent(mock_backend):
    event1 = DummyEvent(event_type="pre_tool_use", data={"tool_call_id": "call_1", "tool_name": "test_tool", "tool_input": {"args": 1}})

    event2 = DummyEvent(event_type="post_tool_use_failure", data={"tool_call_id": "call_1", "error": "error result"})

    mock_backend.get_events.return_value = [event1, event2]

    analyzer = TraceAnalyzer(backend=mock_backend)
    result = await analyzer.analyze_slice("session_1", ["call_1"])

    assert result is not None
    # 1 call, 1 error -> 100% error rate -> incoherent
    assert result.is_coherent is False
    assert "error result" in result.formatted_trace

@pytest.mark.asyncio
async def test_extract_trajectory_with_code(mock_backend):
    # Mock extract_trajectory
    analyzer = TraceAnalyzer(backend=mock_backend)
    analyzer.extract_trajectory = AsyncMock(return_value="Trace history")

    skill = MagicMock()
    skill.skill_id = "test_skill"
    skill.content = "def test():\n    pass"

    result = await analyzer.extract_trajectory_with_code("session_1", skill)
    assert "Trace history" in result
    assert "def test():\n    pass" in result

@pytest.mark.asyncio
async def test_extract_trajectory_no_backend():
    analyzer = TraceAnalyzer(backend=None)
    result = await analyzer.extract_trajectory("session_1", "test_skill")
    assert "unavailable" in result
