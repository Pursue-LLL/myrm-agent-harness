"""Unit tests for Item 150 SqliteTranscriptProjectionSuite.

Tests:
1. Cold-start projection without session files & idempotent secondary bootstrap.
2. Adoption of repeated bodies by created time proximity.
3. Same-second twin ambiguity fail-closed (unstamped).
4. Missing or unknown timestamps fail-closed (unstamped).
5. Genuinely unique content adopts without requiring timestamps.
"""

from __future__ import annotations

import time

from myrm_agent_harness.toolkits.memory.transcript_projection import (
    AdoptionStatus,
    BootstrapContext,
    SessionMessage,
    SqliteTranscriptProjectionStore,
    TranscriptAdoptionEngine,
    TranscriptEntry,
)


def test_cold_start_projection_and_idempotent_bootstrap() -> None:
    """Test cold-start import from SQLite transcript entries and verify secondary bootstrap idempotency."""
    store = SqliteTranscriptProjectionStore(":memory:")
    session_id = "test_sess_cold_start"

    # 1. Seed transcript entries in SQLite SSOT
    entries = [
        TranscriptEntry(
            entry_id="entry_user_1",
            session_id=session_id,
            seq=1,
            role="user",
            content="Hello world",
            created_at_ms=1719662400000,
        ),
        TranscriptEntry(
            entry_id="entry_asst_1",
            session_id=session_id,
            seq=2,
            role="assistant",
            content="Hello! How can I help you?",
            created_at_ms=1719662401000,
            parent_id="entry_user_1",
        ),
    ]
    store.append_transcript_entries(entries)

    # 2. Bootstrap without pre-existing session file
    ctx = BootstrapContext(session_id=session_id, session_key=f"agent:main:{session_id}")
    res1 = store.bootstrap_session(ctx)
    assert res1.bootstrapped is True
    assert res1.imported_messages == 2
    assert res1.already_bootstrapped is False

    # Verify messages projected with transcript_entry_id populated
    messages = store.get_session_messages(session_id)
    assert len(messages) == 2
    assert [m.content for m in messages] == ["Hello world", "Hello! How can I help you?"]
    assert [m.transcript_entry_id for m in messages] == ["entry_user_1", "entry_asst_1"]

    # 3. Secondary bootstrap must be completely idempotent (no duplicate rows)
    res2 = store.bootstrap_session(ctx)
    assert res2.bootstrapped is True
    assert res2.already_bootstrapped is True
    assert res2.imported_messages == 2

    messages_after = store.get_session_messages(session_id)
    assert len(messages_after) == 2
    assert [m.transcript_entry_id for m in messages_after] == ["entry_user_1", "entry_asst_1"]


def test_adopt_repeated_bodies_by_created_time() -> None:
    """Test that repeated content adopts corresponding transcript entries based on created time proximity."""
    engine = TranscriptAdoptionEngine(default_tolerance_ms=2000)
    bare_content = "[System] Your previous turn was interrupted by a gateway restart."

    t0 = 1718965080000  # 10:18:00
    t1 = 1718965140000  # 10:19:00

    entries = [
        TranscriptEntry(
            entry_id="entry_older",
            session_id="sess_rep",
            seq=1,
            role="user",
            content=bare_content,
            created_at_ms=t0,
        ),
        TranscriptEntry(
            entry_id="entry_middle",
            session_id="sess_rep",
            seq=2,
            role="assistant",
            content="middle reply",
            created_at_ms=t0 + 1000,
        ),
        TranscriptEntry(
            entry_id="entry_newer",
            session_id="sess_rep",
            seq=3,
            role="user",
            content=bare_content,
            created_at_ms=t1,
        ),
    ]

    live_messages = [
        SessionMessage(
            message_id="msg_live_1",
            session_id="sess_rep",
            seq=1,
            role="user",
            content=bare_content,
            timestamp_ms=t0 + 40,  # 40ms offset from older
        ),
        SessionMessage(
            message_id="msg_live_2",
            session_id="sess_rep",
            seq=2,
            role="assistant",
            content="middle reply",
            timestamp_ms=t0 + 1000,
        ),
        SessionMessage(
            message_id="msg_live_3",
            session_id="sess_rep",
            seq=3,
            role="user",
            content=bare_content,
            timestamp_ms=t1 + 25,  # 25ms offset from newer
        ),
    ]

    decisions = engine.reconcile(live_messages, entries, tolerance_ms=2000)
    assert len(decisions) == 3

    d1, d2, d3 = decisions
    assert d1.message_id == "msg_live_1"
    assert d1.transcript_entry_id == "entry_older"
    assert d1.status == AdoptionStatus.ADOPTED_BY_TIMESTAMP

    assert d2.message_id == "msg_live_2"
    assert d2.transcript_entry_id == "entry_middle"
    assert d2.status == AdoptionStatus.ADOPTED_UNIQUE

    assert d3.message_id == "msg_live_3"
    assert d3.transcript_entry_id == "entry_newer"
    assert d3.status == AdoptionStatus.ADOPTED_BY_TIMESTAMP


def test_same_second_twins_fail_closed_unstamped() -> None:
    """Twins with identical timestamps within tolerance must remain unstamped fail-closed."""
    engine = TranscriptAdoptionEngine(default_tolerance_ms=2000)
    content = "Repeat statement"
    t_shared = 1718965080000

    entries = [
        TranscriptEntry(
            entry_id="entry_twin_a",
            session_id="sess_twin",
            seq=1,
            role="user",
            content=content,
            created_at_ms=t_shared,
        ),
        TranscriptEntry(
            entry_id="entry_twin_b",
            session_id="sess_twin",
            seq=2,
            role="user",
            content=content,
            created_at_ms=t_shared,
        ),
    ]

    live_messages = [
        SessionMessage(
            message_id="msg_live_twin_1",
            session_id="sess_twin",
            seq=1,
            role="user",
            content=content,
            timestamp_ms=t_shared + 100,
        ),
        SessionMessage(
            message_id="msg_live_twin_2",
            session_id="sess_twin",
            seq=2,
            role="user",
            content=content,
            timestamp_ms=t_shared + 700,
        ),
    ]

    decisions = engine.reconcile(live_messages, entries)
    # Both messages encounter identical twin entries -> fail-closed unstamped
    assert decisions[0].transcript_entry_id is None
    assert decisions[0].status == AdoptionStatus.UNSTAMPED_TWIN_CONFLICT
    assert decisions[1].transcript_entry_id is None
    assert decisions[1].status == AdoptionStatus.UNSTAMPED_TWIN_CONFLICT


def test_unknown_timestamp_fail_closed_unstamped() -> None:
    """Repeated content where candidate or message lacks timestamp must remain unstamped fail-closed."""
    engine = TranscriptAdoptionEngine(default_tolerance_ms=2000)
    repeated_content = "Repeated query"

    entries = [
        TranscriptEntry(
            entry_id="entry_no_time",
            session_id="sess_unknown",
            seq=1,
            role="user",
            content=repeated_content,
            created_at_ms=None,
        ),
        TranscriptEntry(
            entry_id="entry_valid_time",
            session_id="sess_unknown",
            seq=2,
            role="user",
            content=repeated_content,
            created_at_ms=1718965080000,
        ),
    ]

    # Live message with missing timestamp
    live_messages = [
        SessionMessage(
            message_id="msg_missing_ts",
            session_id="sess_unknown",
            seq=1,
            role="user",
            content=repeated_content,
            timestamp_ms=None,
        )
    ]

    decisions = engine.reconcile(live_messages, entries)
    assert len(decisions) == 1
    assert decisions[0].transcript_entry_id is None
    assert decisions[0].status == AdoptionStatus.UNSTAMPED_UNKNOWN_TIME


def test_genuinely_unique_content_adopts_without_timestamp() -> None:
    """Genuinely unique content adopts without requiring any timestamps."""
    engine = TranscriptAdoptionEngine(default_tolerance_ms=2000)
    unique_text = "Unique special command execution"

    entries = [
        TranscriptEntry(
            entry_id="entry_unique_1",
            session_id="sess_unique",
            seq=1,
            role="user",
            content=unique_text,
            created_at_ms=None,  # No timestamp!
        )
    ]

    live_messages = [
        SessionMessage(
            message_id="msg_unique_1",
            session_id="sess_unique",
            seq=1,
            role="user",
            content=unique_text,
            timestamp_ms=None,  # No timestamp!
        )
    ]

    decisions = engine.reconcile(live_messages, entries)
    assert len(decisions) == 1
    assert decisions[0].transcript_entry_id == "entry_unique_1"
    assert decisions[0].status == AdoptionStatus.ADOPTED_UNIQUE
