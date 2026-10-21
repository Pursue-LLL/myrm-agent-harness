"""Unit tests for Cross-Surface Agent Activity Conversation Bridge Pack."""

import time

from myrm_agent_harness.agent.sub_agents.cross_surface_bridge import (
    CrossSurfaceActivityBridge,
    IngressActivityItem,
)


def test_ingest_single_activity() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-001")
    item = IngressActivityItem(
        activity_id="act-001",
        session_key="tauri-session-alpha",
        source_surface="tauri_desktop",
        agent_id="desktop-copilot",
        activity_kind="tool_call",
        preview_text="Reading local file workspace/app.py",
        metadata={"file": "workspace/app.py"},
    )

    snapshot = bridge.ingest_activity(item)
    assert snapshot.chat_id == "chat-bridge-001"
    assert snapshot.total_ingressed_activities == 1
    assert len(snapshot.bounded_recent_activities) == 1
    assert len(snapshot.active_presences) == 1

    presence = snapshot.active_presences[0]
    assert presence.session_key == "tauri-session-alpha"
    assert presence.source_surface == "tauri_desktop"
    assert presence.agent_id == "desktop-copilot"
    assert presence.status == "active"
    assert presence.recent_activities_count == 1


def test_ingest_batch_activities() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-002")
    items = [
        IngressActivityItem(
            activity_id=f"act-cli-{i}",
            session_key="cli-session-42",
            source_surface="cli_tool",
            agent_id="terminal-agent",
            activity_kind="thinking_pulse",
            preview_text=f"Analyzing git diff chunk #{i}",
        )
        for i in range(4)
    ]

    snapshot = bridge.ingest_batch(items)
    assert snapshot.total_ingressed_activities == 4
    assert len(snapshot.bounded_recent_activities) == 4
    assert len(snapshot.active_presences) == 1
    assert snapshot.active_presences[0].recent_activities_count == 4


def test_bounded_preview_text_truncation() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-003")
    oversized_text = "A" * 500
    item = IngressActivityItem(
        activity_id="act-long",
        session_key="cron-job-sync",
        source_surface="cron_job",
        agent_id="nightly-crawler",
        activity_kind="tool_result",
        preview_text=oversized_text,
    )

    snapshot = bridge.ingest_activity(item)
    projected = snapshot.bounded_recent_activities[0]
    assert len(projected.preview_text) == 256
    assert projected.preview_text.endswith("...")


def test_bounded_ring_buffer_eviction() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-004", max_recent_items=10)
    for i in range(15):
        bridge.ingest_activity(
            IngressActivityItem(
                activity_id=f"act-seq-{i}",
                session_key=f"session-{i % 2}",
                source_surface="remote_office_clone",
                agent_id="clone-bot",
                activity_kind="heartbeat",
                preview_text=f"Pulse ping {i}",
            )
        )

    snapshot = bridge.get_snapshot()
    assert snapshot.total_ingressed_activities == 15
    # Must keep strictly only the latest 10 items
    assert len(snapshot.bounded_recent_activities) == 10
    assert snapshot.bounded_recent_activities[-1].activity_id == "act-seq-14"
    assert snapshot.bounded_recent_activities[0].activity_id == "act-seq-5"


def test_presence_status_transition_on_turn_complete() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-005")
    # Step 1: Start turn
    bridge.ingest_activity(
        IngressActivityItem(
            activity_id="act-start",
            session_key="session-t",
            source_surface="tauri_desktop",
            agent_id="agent-x",
            activity_kind="turn_start",
            preview_text="User sent query",
        )
    )
    snap1 = bridge.get_snapshot()
    assert snap1.active_presences[0].status == "active"

    # Step 2: Complete turn
    bridge.ingest_activity(
        IngressActivityItem(
            activity_id="act-end",
            session_key="session-t",
            source_surface="tauri_desktop",
            agent_id="agent-x",
            activity_kind="turn_complete",
            preview_text="Finished response generation",
        )
    )
    snap2 = bridge.get_snapshot()
    assert snap2.active_presences[0].status == "completed"


def test_prune_stale_presences() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-006")
    old_timestamp = time.time() - 400.0

    # Add an expired completed session
    bridge.ingest_activity(
        IngressActivityItem(
            activity_id="act-old-completed",
            session_key="session-old-c",
            source_surface="cli_tool",
            agent_id="cli-1",
            activity_kind="turn_complete",
            preview_text="Old completed task",
            timestamp=old_timestamp,
        )
    )

    # Add an expired active session
    bridge.ingest_activity(
        IngressActivityItem(
            activity_id="act-old-active",
            session_key="session-old-a",
            source_surface="tauri_desktop",
            agent_id="desktop-1",
            activity_kind="tool_call",
            preview_text="Old active task",
            timestamp=old_timestamp,
        )
    )

    pruned = bridge.prune_stale_presences(max_idle_seconds=300.0)
    assert pruned == 2

    snap = bridge.get_snapshot()
    # Completed session was deleted
    assert not any(p.session_key == "session-old-c" for p in snap.active_presences)
    # Active session was downgraded to idle
    idle_pres = next(p for p in snap.active_presences if p.session_key == "session-old-a")
    assert idle_pres.status == "idle"


def test_reset_clears_all() -> None:
    bridge = CrossSurfaceActivityBridge(chat_id="chat-bridge-007")
    bridge.ingest_activity(
        IngressActivityItem(
            activity_id="act-rst",
            session_key="session-rst",
            source_surface="cron_job",
            agent_id="cron-bot",
            activity_kind="heartbeat",
            preview_text="Status check",
        )
    )
    assert bridge.get_snapshot().total_ingressed_activities == 1

    bridge.reset()
    snap = bridge.get_snapshot()
    assert snap.total_ingressed_activities == 0
    assert len(snap.active_presences) == 0
    assert len(snap.bounded_recent_activities) == 0
    assert snap.last_ingressed_at is None
