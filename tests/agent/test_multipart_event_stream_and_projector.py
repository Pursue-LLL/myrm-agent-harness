"""Unit tests for multi-part event stream, SQLite projector, and lossless session replayer.

Verifies:
- Granular event streaming, monotonic sequence counters, and pub-sub fanout.
- Historical event replay across disconnections and reconnects.
- SQLite incremental projection: PART_APPEND, streaming PART_DELTA accumulation, and PART_COMPLETE.
- Multi-part assistant message decomposition (Reasoning, Text, Tool, FilePatch).
- Lossless session state tree reconstruction from projected SQLite data.
- Detection of unclosed in-progress parts during crashes/interruptions.
- Markdown transcript synthesis.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.event_stream import (
    EventKind,
    PartEventStream,
    PartKind,
    PartStatus,
    SessionReplayer,
    SQLitePartProjector,
)


@pytest.mark.asyncio
async def test_part_event_stream_pubsub_and_reconnection_replay() -> None:
    stream = PartEventStream(replay_buffer_capacity=50)

    # 1. Publish initial events before subscription
    evt1 = await stream.publish(
        session_id="sess_1",
        message_id="msg_1",
        part_id="part_1",
        part_kind=PartKind.REASONING,
        event_kind=EventKind.PART_APPEND,
        delta="Analyzing",
    )
    evt2 = await stream.publish(
        session_id="sess_1",
        message_id="msg_1",
        part_id="part_1",
        part_kind=PartKind.REASONING,
        event_kind=EventKind.PART_DELTA,
        delta=" requirements...",
    )

    assert evt1.sequence_number == 1
    assert evt2.sequence_number == 2
    assert stream.current_sequence == 2

    # 2. Reconnecting subscriber replaying from sequence 0
    received: list[str] = []

    async def consume_stream() -> None:
        async for event in stream.subscribe(since_sequence=0):
            received.append(event.delta)
            if event.sequence_number == 3:
                break

    consumer_task = asyncio.create_task(consume_stream())

    # Allow consumer to process replay
    await asyncio.sleep(0.02)

    # 3. Publish live event 3
    await stream.publish(
        session_id="sess_1",
        message_id="msg_1",
        part_id="part_1",
        part_kind=PartKind.REASONING,
        event_kind=EventKind.PART_COMPLETE,
        delta="",
        payload={"status": PartStatus.COMPLETED.value},
    )

    await asyncio.wait_for(consumer_task, timeout=2.0)
    assert received == ["Analyzing", " requirements...", ""]


@pytest.mark.asyncio
async def test_sqlite_projector_incremental_deltas_and_part_lifecycle() -> None:
    projector = SQLitePartProjector(":memory:")
    stream = PartEventStream()

    # Streaming typewriter-style TextPart
    p_id = "text_part_1"
    m_id = "msg_100"
    s_id = "sess_alpha"

    # Step A: Append
    evt_a = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id=p_id,
        part_kind=PartKind.TEXT,
        event_kind=EventKind.PART_APPEND,
        delta="Hello",
    )
    await projector.project_event(evt_a)

    # Step B: Streaming Deltas
    for chunk in [" world", "! How", " can I help?"]:
        evt_d = await stream.publish(
            session_id=s_id,
            message_id=m_id,
            part_id=p_id,
            part_kind=PartKind.TEXT,
            event_kind=EventKind.PART_DELTA,
            delta=chunk,
        )
        await projector.project_event(evt_d)

    # Step C: Complete
    evt_c = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id=p_id,
        part_kind=PartKind.TEXT,
        event_kind=EventKind.PART_COMPLETE,
        payload={"status": PartStatus.COMPLETED.value, "duration_ms": 142.5},
    )
    await projector.project_event(evt_c)

    # Verify projected state in SQLite
    parts = await projector.get_parts_for_message(m_id)
    assert len(parts) == 1
    p = parts[0]
    assert p["part_id"] == p_id
    assert p["part_kind"] == PartKind.TEXT.value
    assert p["content"] == "Hello world! How can I help?"
    assert p["status"] == PartStatus.COMPLETED.value
    assert p["duration_ms"] == 142.5

    await projector.close()


@pytest.mark.asyncio
async def test_multi_part_assistant_turn_lifecycle() -> None:
    projector = SQLitePartProjector(":memory:")
    stream = PartEventStream()

    s_id = "sess_lifecycle"
    m_id = "msg_turn_1"

    # 1. Reasoning Part
    r_evt = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_r1",
        part_kind=PartKind.REASONING,
        event_kind=EventKind.PART_APPEND,
        delta="Planning file read operation.",
        payload={"status": PartStatus.COMPLETED.value, "duration_ms": 50.0},
    )
    await projector.project_event(r_evt)

    # 2. Tool Invocation Part
    ti_evt = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_ti1",
        part_kind=PartKind.TOOL_INVOCATION,
        event_kind=EventKind.PART_APPEND,
        delta="",
        payload={
            "tool_call_id": "call_123",
            "tool_name": "read_file",
            "arguments": '{"path": "config.yaml"}',
            "status": PartStatus.COMPLETED.value,
        },
    )
    await projector.project_event(ti_evt)

    # 3. Tool Result Part
    tr_evt = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_tr1",
        part_kind=PartKind.TOOL_RESULT,
        event_kind=EventKind.PART_APPEND,
        delta="database_url: sqlite:///app.db",
        payload={
            "tool_call_id": "call_123",
            "tool_name": "read_file",
            "status": PartStatus.COMPLETED.value,
            "duration_ms": 12.0,
        },
    )
    await projector.project_event(tr_evt)

    # 4. File Patch Part
    fp_evt = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_fp1",
        part_kind=PartKind.FILE_PATCH,
        event_kind=EventKind.PART_APPEND,
        delta="--- config.yaml\n+++ config.yaml\n+timeout: 30",
        payload={
            "target_file": "config.yaml",
            "status": PartStatus.COMPLETED.value,
        },
    )
    await projector.project_event(fp_evt)

    session_parts = await projector.get_session_parts(s_id)
    assert len(session_parts) == 4
    kinds = [p["part_kind"] for p in session_parts]
    assert kinds == [
        PartKind.REASONING.value,
        PartKind.TOOL_INVOCATION.value,
        PartKind.TOOL_RESULT.value,
        PartKind.FILE_PATCH.value,
    ]

    await projector.close()


@pytest.mark.asyncio
async def test_session_replayer_lossless_recovery_and_interruption_detection() -> None:
    projector = SQLitePartProjector(":memory:")
    stream = PartEventStream()
    replayer = SessionReplayer(projector)

    s_id = "sess_replayer"
    m_id = "msg_turn_1"

    # Part 1: Completed text
    p1 = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_text",
        part_kind=PartKind.TEXT,
        event_kind=EventKind.PART_APPEND,
        delta="Starting execution...",
    )
    await projector.project_event(p1)
    p1_comp = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_text",
        part_kind=PartKind.TEXT,
        event_kind=EventKind.PART_COMPLETE,
        payload={"status": PartStatus.COMPLETED.value},
    )
    await projector.project_event(p1_comp)

    # Part 2: Interrupted Tool Invocation (remains IN_PROGRESS due to unexpected crash)
    p2 = await stream.publish(
        session_id=s_id,
        message_id=m_id,
        part_id="part_hanging_tool",
        part_kind=PartKind.TOOL_INVOCATION,
        event_kind=EventKind.PART_APPEND,
        delta='{"command": "pytest"}',
    )
    await projector.project_event(p2)

    # Replay session snapshot
    snapshot = await replayer.replay_session(s_id)

    assert snapshot.session_id == s_id
    assert snapshot.total_parts == 2
    assert snapshot.has_interruption is True
    assert len(snapshot.unclosed_parts) == 1

    hanging = snapshot.unclosed_parts[0]
    assert hanging.part_id == "part_hanging_tool"
    assert hanging.kind == PartKind.TOOL_INVOCATION
    assert hanging.status == PartStatus.IN_PROGRESS

    # Render Markdown transcript
    transcript = replayer.render_markdown_transcript(snapshot)
    assert f"# Session Transcript: {s_id}" in transcript
    assert "Session contains 1 unclosed part(s)!" in transcript
    assert "Starting execution..." in transcript

    await projector.close()
