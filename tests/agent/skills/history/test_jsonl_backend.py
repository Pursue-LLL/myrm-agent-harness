"""Integration tests for JsonlHistoryBackend — real file system operations.

Test coverage:
1. append_history: Write history records to JSONL files
2. list_history: Read and parse history from JSONL files
3. get_history_count: Count total history entries
4. File system operations: Directory creation, file handling, error cases
5. Thread/session ID tracking: Business context preservation
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.history import JsonlHistoryBackend, SkillHistoryRecord


@pytest.fixture
def temp_history_dir():
    """Create a temporary directory for history storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def backend(temp_history_dir: Path) -> JsonlHistoryBackend:
    """Create JsonlHistoryBackend with temporary storage."""
    return JsonlHistoryBackend(history_root=temp_history_dir)


@pytest.mark.asyncio
async def test_append_and_list_history(backend: JsonlHistoryBackend, temp_history_dir: Path) -> None:
    """Test basic append and list operations."""
    record = SkillHistoryRecord(
        action="save",
        author="user123",
        timestamp=datetime.now(),
        file_path="skills/test_skill/SKILL.md",
        prev_content=None,
        new_content="---\nname: test\n---\n# Test",
        thread_id="thread_001",
        session_id="session_001",
    )

    await backend.append_history("test_skill", record)

    history_file = temp_history_dir / "test_skill.jsonl"
    assert history_file.exists()

    records = await backend.list_history("test_skill")
    assert len(records) == 1
    assert records[0].action == "save"
    assert records[0].author == "user123"
    assert records[0].thread_id == "thread_001"
    assert records[0].session_id == "session_001"


@pytest.mark.asyncio
async def test_multiple_records_ordering(backend: JsonlHistoryBackend) -> None:
    """Test that multiple records are stored and retrieved in correct order."""
    timestamps = [
        datetime(2024, 1, 1, 10, 0, 0),
        datetime(2024, 1, 1, 11, 0, 0),
        datetime(2024, 1, 1, 12, 0, 0),
    ]

    for i, ts in enumerate(timestamps):
        record = SkillHistoryRecord(
            action=f"action_{i}",
            author="user123",
            timestamp=ts,
            file_path=f"file_{i}",
            prev_content=f"prev_{i}",
            new_content=f"new_{i}",
        )
        await backend.append_history("test_skill", record)

    records = await backend.list_history("test_skill")
    assert len(records) == 3

    assert records[0].action == "action_2"
    assert records[1].action == "action_1"
    assert records[2].action == "action_0"


@pytest.mark.asyncio
async def test_get_history_count(backend: JsonlHistoryBackend) -> None:
    """Test get_history_count returns correct count."""
    count = await backend.get_history_count("test_skill")
    assert count == 0

    for i in range(5):
        record = SkillHistoryRecord(
            action=f"action_{i}",
            author="user123",
            timestamp=datetime.now(),
            file_path=f"file_{i}",
            prev_content=None,
            new_content=f"content_{i}",
        )
        await backend.append_history("test_skill", record)

    count = await backend.get_history_count("test_skill")
    assert count == 5


@pytest.mark.asyncio
async def test_skill_isolation(backend: JsonlHistoryBackend) -> None:
    """Test that different skills have isolated history."""
    record_a = SkillHistoryRecord(
        action="save",
        author="user123",
        timestamp=datetime.now(),
        file_path="skill_a/SKILL.md",
        prev_content=None,
        new_content="content_a",
    )
    await backend.append_history("skill_a", record_a)

    record_b = SkillHistoryRecord(
        action="save",
        author="user123",
        timestamp=datetime.now(),
        file_path="skill_b/SKILL.md",
        prev_content=None,
        new_content="content_b",
    )
    await backend.append_history("skill_b", record_b)

    skill_a_history = await backend.list_history("skill_a")
    skill_b_history = await backend.list_history("skill_b")

    assert len(skill_a_history) == 1
    assert len(skill_b_history) == 1
    assert skill_a_history[0].file_path == "skill_a/SKILL.md"
    assert skill_b_history[0].file_path == "skill_b/SKILL.md"


@pytest.mark.asyncio
async def test_list_nonexistent_history(backend: JsonlHistoryBackend) -> None:
    """Test listing history for nonexistent skill returns empty list."""
    records = await backend.list_history("nonexistent_skill")
    assert records == []


@pytest.mark.asyncio
async def test_history_with_all_metadata_fields(backend: JsonlHistoryBackend) -> None:
    """Test that all metadata fields are preserved."""
    record = SkillHistoryRecord(
        action="save",
        author="user123",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
        file_path="skills/test_skill/SKILL.md",
        prev_content="old content",
        new_content="new content",
        thread_id="thread_123",
        session_id="session_456",
        request_id="request_789",
        user_agent="TestAgent/1.0",
        scanner={"engine": "bandit", "version": "1.0"},
        metadata={"key1": "value1", "key2": "value2"},
    )

    await backend.append_history("test_skill", record)
    records = await backend.list_history("test_skill")

    assert len(records) == 1
    retrieved = records[0]
    assert retrieved.action == "save"
    assert retrieved.author == "user123"
    assert retrieved.file_path == "skills/test_skill/SKILL.md"
    assert retrieved.prev_content == "old content"
    assert retrieved.new_content == "new content"
    assert retrieved.thread_id == "thread_123"
    assert retrieved.session_id == "session_456"
    assert retrieved.request_id == "request_789"
    assert retrieved.user_agent == "TestAgent/1.0"
    assert retrieved.scanner == {"engine": "bandit", "version": "1.0"}
    assert retrieved.metadata == {"key1": "value1", "key2": "value2"}


@pytest.mark.asyncio
async def test_jsonl_format_correctness(backend: JsonlHistoryBackend, temp_history_dir: Path) -> None:
    """Test that JSONL file format is correct (one JSON object per line)."""
    for i in range(3):
        record = SkillHistoryRecord(
            action=f"action_{i}",
            author="user123",
            timestamp=datetime.now(),
            file_path=f"file_{i}",
            prev_content=None,
            new_content=f"content_{i}",
        )
        await backend.append_history("test_skill", record)

    history_file = temp_history_dir / "test_skill.jsonl"
    with open(history_file, encoding="utf-8") as f:
        lines = f.readlines()

    assert len(lines) == 3
    for line in lines:
        data = json.loads(line)
        assert "action" in data
        assert "author" in data
        assert "timestamp" in data


@pytest.mark.asyncio
async def test_concurrent_append_safety(backend: JsonlHistoryBackend) -> None:
    """Test that concurrent appends don't corrupt the file."""
    import asyncio

    async def append_record(index: int) -> None:
        record = SkillHistoryRecord(
            action=f"action_{index}",
            author="user123",
            timestamp=datetime.now(),
            file_path=f"file_{index}",
            prev_content=None,
            new_content=f"content_{index}",
        )
        await backend.append_history("test_skill", record)

    await asyncio.gather(*[append_record(i) for i in range(10)])

    count = await backend.get_history_count("test_skill")
    assert count == 10

    records = await backend.list_history("test_skill")
    assert len(records) == 10


@pytest.mark.asyncio
async def test_history_limit(backend: JsonlHistoryBackend) -> None:
    """Test list_history with limit parameter."""
    for i in range(10):
        record = SkillHistoryRecord(
            action=f"action_{i}",
            author="user123",
            timestamp=datetime.now(),
            file_path=f"file_{i}",
            prev_content=None,
            new_content=f"content_{i}",
        )
        await backend.append_history("test_skill", record)

    records_5 = await backend.list_history("test_skill", limit=5)
    assert len(records_5) == 5

    records_3 = await backend.list_history("test_skill", limit=3)
    assert len(records_3) == 3

    assert records_3[0].action == "action_9"
    assert records_3[1].action == "action_8"
    assert records_3[2].action == "action_7"
