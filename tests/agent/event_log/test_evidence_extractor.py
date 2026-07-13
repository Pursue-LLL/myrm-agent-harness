import pytest

from myrm_agent_harness.agent.event_log.evidence_extractor import SessionEvidenceExtractor
from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.event_log.types import EventFilter, StructuredEvent


def make_event(seq: int, ts: float, event_type: str, data: dict) -> StructuredEvent:
    """Helper to create StructuredEvent with correct field order."""
    return StructuredEvent(
        sequence=seq,
        timestamp=ts,
        event_type=event_type,
        session_id="test",
        data=data,
    )


class MockEventLogBackend(EventLogBackend):
    """Mock backend for testing evidence extraction."""

    def __init__(self, events: list[StructuredEvent]):
        self._events = events

    async def log_event(self, session_id: str, event: StructuredEvent) -> None:
        pass

    async def get_events(self, session_id: str, filter: EventFilter | None = None) -> list[StructuredEvent]:
        return self._events

    async def get_all_session_ids(self) -> list[str]:
        return ["test_session"]


@pytest.mark.asyncio
async def test_extract_digest_with_file_operations():
    """Test that file operations are correctly tracked as hotspots."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Refactor database module"}),
        make_event(1, 2.0, "tool_start", {"tool_name": "file_read_tool", "file_path": "database.py"}),
        make_event(2, 3.0, "tool_start", {"tool_name": "file_read_tool", "file_path": "database.py"}),
        make_event(3, 4.0, "tool_start", {"tool_name": "file_write_tool", "file_path": "database.py"}),
        make_event(4, 5.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert digest.session_id == "test"
    assert digest.task_intent == "Refactor database module"
    assert len(digest.hotspots) == 1
    assert digest.hotspots[0].file_path == "database.py"
    assert digest.hotspots[0].read_count == 2
    assert digest.hotspots[0].write_count == 1
    assert digest.success_rate == 1.0
    assert digest.duration_ms == 4000.0


@pytest.mark.asyncio
async def test_extract_digest_with_tool_failures():
    """Test that tool failures are correctly extracted as anti-patterns."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Fix database connection"}),
        make_event(1, 2.0, "tool_start", {"tool_name": "bash_code_execute_tool"}),
        make_event(
            2,
            3.0,
            "tool_failure",
            {"tool_name": "bash_code_execute_tool", "error": "Connection refused: database not running", "command": "psql -h localhost"},
        ),
        make_event(3, 4.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.anti_patterns) == 1
    assert digest.anti_patterns[0].failed_tool == "bash_code_execute_tool"
    assert "Connection refused" in digest.anti_patterns[0].error_signature
    assert digest.anti_patterns[0].user_correction is None
    assert digest.success_rate == 0.0  # 1 tool, 1 error


@pytest.mark.asyncio
async def test_extract_digest_with_user_interruption():
    """Test that user interruptions are tied to anti-patterns as corrections."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Deploy to production"}),
        make_event(1, 2.0, "tool_start", {"tool_name": "bash_code_execute_tool"}),
        make_event(2, 3.0, "tool_failure", {"tool_name": "bash_code_execute_tool", "error": "Permission denied: cannot write to /prod"}),
        make_event(3, 4.0, "user_interruption", {"correction_message": "Need to use sudo for production deployment"}),
        make_event(4, 5.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.anti_patterns) == 1
    assert digest.anti_patterns[0].failed_tool == "bash_code_execute_tool"
    assert "Permission denied" in digest.anti_patterns[0].error_signature
    assert digest.anti_patterns[0].user_correction == "Need to use sudo for production deployment"


@pytest.mark.asyncio
async def test_extract_digest_empty_session():
    """Test that empty sessions return None."""
    backend = MockEventLogBackend([])
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is None


@pytest.mark.asyncio
async def test_extract_digest_hotspots_sorting():
    """Test that hotspots are sorted by write_count then read_count."""
    seq = 0
    events = [make_event(seq := seq + 1, 1.0, "session_start", {"query": "Test"})]

    # models.py: 10 reads, 2 writes
    for i in range(2, 12):
        events.append(make_event(seq := seq + 1, float(i), "tool_start", {"tool_name": "file_read_tool", "file_path": "models.py"}))
    for i in range(12, 14):
        events.append(make_event(seq := seq + 1, float(i), "tool_start", {"tool_name": "file_write_tool", "file_path": "models.py"}))

    # database.py: 5 reads, 5 writes (should be first due to higher write_count)
    for i in range(14, 19):
        events.append(make_event(seq := seq + 1, float(i), "tool_start", {"tool_name": "file_read_tool", "file_path": "database.py"}))
    for i in range(19, 24):
        events.append(make_event(seq := seq + 1, float(i), "tool_start", {"tool_name": "file_write_tool", "file_path": "database.py"}))

    events.append(make_event(seq := seq + 1, 25.0, "session_end", {}))

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.hotspots) == 2
    # database.py should be first (5 writes > 2 writes)
    assert digest.hotspots[0].file_path == "database.py"
    assert digest.hotspots[0].write_count == 5
    assert digest.hotspots[0].read_count == 5
    # models.py should be second
    assert digest.hotspots[1].file_path == "models.py"
    assert digest.hotspots[1].write_count == 2
    assert digest.hotspots[1].read_count == 10


@pytest.mark.asyncio
async def test_extract_digest_anti_patterns_limit():
    """Test that anti-patterns are limited to last 10."""
    seq = 0
    events = [make_event(seq := seq + 1, 1.0, "session_start", {"query": "Test"})]

    # Generate 15 tool failures
    for i in range(2, 17):
        events.append(make_event(seq := seq + 1, float(i), "tool_failure", {"tool_name": f"tool_{i}", "error": f"Error {i}"}))

    events.append(make_event(seq := seq + 1, 18.0, "session_end", {}))

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    # Should only keep last 10 anti-patterns
    assert len(digest.anti_patterns) == 10
    # Should be tool_7 to tool_16 (last 10)
    assert digest.anti_patterns[0].failed_tool == "tool_7"
    assert digest.anti_patterns[-1].failed_tool == "tool_16"


@pytest.mark.asyncio
async def test_extract_digest_hotspots_limit():
    """Test that hotspots are limited to top 20."""
    seq = 0
    events = [make_event(seq := seq + 1, 1.0, "session_start", {"query": "Test"})]

    # Generate 25 different file operations
    for i in range(2, 27):
        events.append(make_event(seq := seq + 1, float(i), "tool_start", {"tool_name": "file_write_tool", "file_path": f"file_{i}.py"}))

    events.append(make_event(seq := seq + 1, 28.0, "session_end", {}))

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    # Should only keep top 20 hotspots
    assert len(digest.hotspots) <= 20


@pytest.mark.asyncio
async def test_extract_digest_without_session_start():
    """Test that extractor handles missing session_start event gracefully."""
    events = [
        make_event(0, 1.0, "tool_start", {"tool_name": "file_read_tool", "file_path": "test.py"}),
        make_event(1, 2.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert digest.task_intent is None  # No session_start means no intent
    assert len(digest.hotspots) == 1
    assert digest.hotspots[0].file_path == "test.py"


@pytest.mark.asyncio
async def test_extract_digest_without_session_end():
    """Test that extractor handles missing session_end event gracefully."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Test"}),
        make_event(1, 2.0, "tool_start", {"tool_name": "file_read_tool", "file_path": "test.py"}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert digest.task_intent == "Test"
    assert digest.duration_ms == 0.0  # No session_end means duration is 0


@pytest.mark.asyncio
async def test_extract_digest_with_short_error_message():
    """Test that tool failures with very short error messages are ignored."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Test"}),
        make_event(1, 2.0, "tool_failure", {"tool_name": "bash_code_execute_tool", "error": "err"}),  # Too short (<= 5 chars)
        make_event(2, 3.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.anti_patterns) == 0  # Should be ignored


@pytest.mark.asyncio
async def test_extract_digest_with_unknown_tool_name():
    """Test that tool failures with unknown tool names are ignored."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Test"}),
        make_event(1, 2.0, "tool_failure", {"tool_name": "unknown", "error": "Some error message here"}),
        make_event(2, 3.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.anti_patterns) == 0  # Should be ignored


@pytest.mark.asyncio
async def test_extract_digest_with_late_user_interruption():
    """Test that user interruptions too late after tool failure are not tied to anti-patterns."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Test"}),
        make_event(1, 2.0, "tool_failure", {"tool_name": "bash_code_execute_tool", "error": "Connection failed"}),
        make_event(2, 400.0, "user_interruption", {"correction_message": "Late correction"}),  # > 300s later
        make_event(3, 401.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.anti_patterns) == 1
    # The user_correction should NOT be applied (too late)
    assert digest.anti_patterns[0].user_correction is None


@pytest.mark.asyncio
async def test_extract_digest_hotspots_use_canonical_path_field():
    """Test hotspots resolve workspace paths from canonical 'path' tool args."""
    events = [
        make_event(0, 1.0, "session_start", {"query": "Refactor auth"}),
        make_event(1, 2.0, "tool_start", {"tool_name": "file_read_tool", "path": "src/auth.py"}),
        make_event(2, 3.0, "tool_start", {"tool_name": "grep_tool", "path": "src/auth.py", "pattern": "token"}),
        make_event(3, 4.0, "session_end", {}),
    ]

    backend = MockEventLogBackend(events)
    extractor = SessionEvidenceExtractor(backend)

    digest = await extractor.extract_digest("test")

    assert digest is not None
    assert len(digest.hotspots) == 1
    assert digest.hotspots[0].file_path == "src/auth.py"
    assert digest.hotspots[0].read_count == 2
    assert digest.hotspots[0].write_count == 0
