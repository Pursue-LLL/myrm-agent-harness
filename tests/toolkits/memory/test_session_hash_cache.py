"""Test session-level hash cache for in-conversation deduplication."""

import pytest

from myrm_agent_harness.toolkits.memory.session import MemorySession


@pytest.fixture
def mock_manager():
    """Mock MemoryManager."""
    from myrm_agent_harness.toolkits.memory._internal.hash_utils import NormalizationLevel

    class MockConfig:
        class dedup:  # noqa: N801
            normalization_level = NormalizationLevel.FULL

    class MockManager:
        user_id = "local"
        config = MockConfig()

        async def store_batch(self, memories):
            return memories

    return MockManager()


def test_session_dedup_knowledge(mock_manager):
    """Session should deduplicate identical knowledge within conversation."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    mem1 = session.add_knowledge("Redis timeout is 5 seconds")
    assert mem1 is not None

    mem2 = session.add_knowledge("Redis timeout is 5 seconds")
    assert mem2 is None, "Duplicate knowledge should return None"

    assert session.buffer_size == 1


def test_session_dedup_events(mock_manager):
    """Session should deduplicate identical events within conversation."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    mem1 = session.add_event("User logged in at 10:00")
    assert mem1 is not None

    mem2 = session.add_event("User logged in at 10:00")
    assert mem2 is None, "Duplicate event should return None"

    assert session.buffer_size == 1


def test_session_dedup_rules(mock_manager):
    """Session should deduplicate identical rules within conversation."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    mem1 = session.add_rule(trigger="user asks for help", action="provide documentation")
    assert mem1 is not None

    mem2 = session.add_rule(trigger="user asks for help", action="provide documentation")
    assert mem2 is None, "Duplicate rule should return None"

    assert session.buffer_size == 1


def test_session_dedup_normalization(mock_manager):
    """Session should normalize content before hashing."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    variants = [
        "Redis timeout is 5 seconds",
        "Redis timeout is 5 seconds!",
        "Redis   timeout   is   5   seconds",
        "redis timeout is 5 seconds",
        "Redis timeout is 5 seconds.",
    ]

    for idx, content in enumerate(variants):
        mem = session.add_knowledge(content)
        if idx == 0:
            assert mem is not None, "First variant should be added"
        else:
            assert mem is None, f"Variant {idx} should be deduplicated: {content}"

    assert session.buffer_size == 1


def test_session_hash_clears_on_flush(mock_manager):
    """Hash cache should clear when session flushes."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    session.add_knowledge("First knowledge")
    assert session.buffer_size == 1
    assert len(session._content_hashes) == 1

    session.discard()
    assert session.buffer_size == 0
    assert len(session._content_hashes) == 0, "Hash cache should clear on discard"


@pytest.mark.asyncio
async def test_session_hash_clears_after_flush(mock_manager):
    """Hash cache should clear after async flush."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    session.add_knowledge("First knowledge")
    assert len(session._content_hashes) == 1

    await session.flush()
    assert len(session._content_hashes) == 0, "Hash cache should clear after flush"


def test_session_allows_different_content(mock_manager):
    """Session should allow genuinely different content."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    mem1 = session.add_knowledge("Redis timeout is 5 seconds")
    mem2 = session.add_knowledge("PostgreSQL pool size is 10")
    mem3 = session.add_knowledge("System uses async processing")

    assert mem1 is not None
    assert mem2 is not None
    assert mem3 is not None
    assert session.buffer_size == 3


def test_session_unicode_normalization(mock_manager):
    """Session should normalize Unicode variants."""
    session = MemorySession(manager=mock_manager, chat_id="chat1")

    mem1 = session.add_knowledge("café")
    mem2 = session.add_knowledge("café")
    mem3 = session.add_knowledge("CAFÉ")

    assert mem1 is not None
    assert mem2 is None, "Unicode variant should be deduplicated"
    assert mem3 is None, "Case variant should be deduplicated"
    assert session.buffer_size == 1
