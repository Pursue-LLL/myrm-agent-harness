"""Unit tests for Snapshot Lag Aware Memory Freshness and Disk Verification Contract Suite."""

from __future__ import annotations

from myrm_agent_harness.agent.middlewares.memory_context.snapshot_freshness import (
    SnapshotFreshnessTracker,
)


def test_init_session_snapshot_digest() -> None:
    tracker = SnapshotFreshnessTracker()
    digest = tracker.init_session_snapshot(
        session_id="session_test_01",
        initial_content="User preference: theme=dark, lang=zh",
        items_count=2,
    )

    assert digest.session_id == "session_test_01"
    assert digest.digest.startswith("snap_")
    assert digest.initial_items_count == 2

    state = tracker.get_state("session_test_01")
    assert state.is_dirty is False
    assert state.latest_disk_version == 1
    assert len(state.deltas) == 0


def test_record_write_and_dirty_flag() -> None:
    tracker = SnapshotFreshnessTracker()
    tracker.init_session_snapshot(session_id="session_test_02", initial_content="init")

    # Turn 1: Write an updated preference
    state1 = tracker.record_write(
        session_id="session_test_02",
        key="editor_preference",
        content="use vim mode",
        turn_index=1,
        action="update",
    )
    assert state1.is_dirty is True
    assert state1.latest_disk_version == 2
    assert len(state1.deltas) == 1
    assert state1.deltas[0].key == "editor_preference"

    # Turn 2: Write another preference, update existing
    state2 = tracker.record_write(
        session_id="session_test_02",
        key="editor_preference",
        content="use emacs mode",
        turn_index=2,
        action="update",
    )
    assert state2.latest_disk_version == 3
    assert len(state2.deltas) == 1
    assert state2.deltas[0].content == "use emacs mode"

    # Turn 3: Add new key
    state3 = tracker.record_write(
        session_id="session_test_02",
        key="timezone",
        content="UTC+8",
        turn_index=3,
        action="create",
    )
    assert len(state3.deltas) == 2


def test_direct_disk_read_hint_generation() -> None:
    tracker = SnapshotFreshnessTracker()
    tracker.init_session_snapshot(session_id="session_test_03")

    # Clean state: No hint alarm
    hint_clean = tracker.generate_disk_read_hint("session_test_03")
    assert hint_clean.is_dirty is False
    assert "未发生跨轮脏写入" in hint_clean.hint_message
    assert len(hint_clean.affected_keys) == 0

    # Mutate disk memory
    tracker.record_write(
        session_id="session_test_03",
        key="main_branch",
        content="main (renamed from master)",
        turn_index=4,
    )

    hint_dirty = tracker.generate_disk_read_hint("session_test_03")
    assert hint_dirty.is_dirty is True
    assert "main_branch" in hint_dirty.affected_keys
    assert "【记忆快照感知契约】" in hint_dirty.hint_message
    assert "优先直接调用内存查询工具读取底层持久磁盘" in hint_dirty.hint_message


def test_render_delta_patch_block() -> None:
    tracker = SnapshotFreshnessTracker()
    tracker.init_session_snapshot(session_id="session_test_04")

    # Clean patch is empty
    empty_patch = tracker.render_delta_patch("session_test_04")
    assert empty_patch.formatted_block == ""
    assert len(empty_patch.patches) == 0

    # Add writes
    tracker.record_write(
        session_id="session_test_04",
        key="db_port",
        content="5433",
        turn_index=2,
        action="update",
    )
    tracker.record_write(
        session_id="session_test_04",
        key="deploy_env",
        content="staging",
        turn_index=3,
        action="create",
    )

    patch_block = tracker.render_delta_patch("session_test_04")
    assert "[SESSION MEMORY DELTA PATCH" in patch_block.header
    assert len(patch_block.patches) == 2
    assert "- [UPDATE] `db_port`: 5433 (落盘轮次: T2)" in patch_block.formatted_block
    assert "- [CREATE] `deploy_env`: staging (落盘轮次: T3)" in patch_block.formatted_block
    assert "其真实性严格覆盖系统初始快照" in patch_block.formatted_block


def test_reset_session() -> None:
    tracker = SnapshotFreshnessTracker()
    tracker.init_session_snapshot(session_id="session_test_05")
    tracker.record_write("session_test_05", "k", "v")

    assert tracker.get_state("session_test_05").is_dirty is True
    tracker.reset_session("session_test_05")

    # After reset, defaults to fresh empty state
    state_after = tracker.get_state("session_test_05")
    assert state_after.is_dirty is False
    assert len(state_after.deltas) == 0
