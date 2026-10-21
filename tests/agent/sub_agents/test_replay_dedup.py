"""Unit tests for Multi-Agent Tool Replay History Deduplication & Status Harmonizer (Item 57)."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.replay_dedup import (
    MergedReplayBatch,
    SubagentStatusHarmonizer,
    ToolReplayHistoryMerger,
    ToolReplayItem,
    ToolReplayKindEnum,
    ToolReplayStatusEnum,
)


def _make_tool_item(
    call_id: str,
    tool_name: str,
    kind: ToolReplayKindEnum = ToolReplayKindEnum.READ_ONLY,
    status: ToolReplayStatusEnum = ToolReplayStatusEnum.COMPLETED,
    tokens: int = 100,
    subagent_id: str = "agent-worker-01",
) -> ToolReplayItem:
    return ToolReplayItem(
        call_id=call_id,
        tool_name=tool_name,
        kind=kind,
        args={"target_path": f"/workspace/{call_id}.py", "depth": 1},
        result_summary=f"Result for {call_id}",
        status=status,
        start_time=1000.0,
        end_time=1001.0,
        estimated_tokens=tokens,
        subagent_id=subagent_id,
    )


class TestToolReplayHistoryMerger:
    """Test suite for consecutive read-only tool history deduplication and merging."""

    def test_empty_items_yields_zero_metrics(self) -> None:
        merger = ToolReplayHistoryMerger()
        res = merger.merge_history(session_id="sess-01", items=[])

        assert res.original_items_count == 0
        assert res.deduplicated_items_count == 0
        assert res.tokens_saved == 0
        assert res.reduction_ratio == 0.0
        assert len(res.batches) == 0
        assert len(res.unmerged_items) == 0

    def test_consecutive_read_only_tools_merged_into_batch(self) -> None:
        merger = ToolReplayHistoryMerger(min_merge_count=2, compact_overhead_tokens=30)
        items = [
            _make_tool_item("c1", "read_file", tokens=120),
            _make_tool_item("c2", "read_file", tokens=130),
            _make_tool_item("c3", "read_file", tokens=150),
        ]

        res = merger.merge_history(session_id="sess-02", items=items)

        assert res.original_items_count == 3
        assert res.deduplicated_items_count == 1
        assert len(res.batches) == 1
        assert len(res.unmerged_items) == 0

        batch: MergedReplayBatch = res.batches[0]
        assert batch.tool_name == "read_file"
        assert batch.merged_count == 3
        assert batch.item_ids == ("c1", "c2", "c3")
        assert batch.original_tokens == 400
        # compact = 30 + (3 * 5) = 45 tokens
        assert batch.compact_tokens == 45
        assert batch.tokens_saved == 355
        assert res.tokens_saved == 355
        assert res.reduction_ratio > 0.8

    def test_mutating_tools_never_merged(self) -> None:
        merger = ToolReplayHistoryMerger()
        items = [
            _make_tool_item("r1", "read_file", tokens=100),
            _make_tool_item("w1", "write_file", kind=ToolReplayKindEnum.MUTATING, tokens=200),
            _make_tool_item("r2", "read_file", tokens=100),
            _make_tool_item("r3", "read_file", tokens=100),
        ]

        res = merger.merge_history(session_id="sess-03", items=items)

        assert res.original_items_count == 4
        # r1 is single (not merged), w1 is mutating (not merged), r2+r3 are merged into 1 batch
        # Deduplicated = 1 (r1) + 1 (w1) + 1 (batch r2-r3) = 3
        assert res.deduplicated_items_count == 3
        assert len(res.batches) == 1
        assert res.batches[0].item_ids == ("r2", "r3")
        assert len(res.unmerged_items) == 2
        assert [it.call_id for it in res.unmerged_items] == ["r1", "w1"]

    def test_different_subagents_isolated(self) -> None:
        merger = ToolReplayHistoryMerger()
        items = [
            _make_tool_item("c1", "read_file", subagent_id="agent-01"),
            _make_tool_item("c2", "read_file", subagent_id="agent-02"),
        ]

        res = merger.merge_history(session_id="sess-04", items=items)
        # Because subagent_ids differ, streak flushes: neither meets min_merge_count of 2
        assert len(res.batches) == 0
        assert len(res.unmerged_items) == 2

    def test_max_batch_size_cap(self) -> None:
        merger = ToolReplayHistoryMerger(min_merge_count=2, max_batch_size=3)
        items = [_make_tool_item(f"c{i}", "grep", tokens=50) for i in range(7)]

        res = merger.merge_history(session_id="sess-05", items=items)
        # 7 items with max_batch_size=3 -> Batch(3) + Batch(3) + unmerged(1)
        assert len(res.batches) == 2
        assert res.batches[0].merged_count == 3
        assert res.batches[1].merged_count == 3
        assert len(res.unmerged_items) == 1
        assert res.unmerged_items[0].call_id == "c6"


class TestSubagentStatusHarmonizer:
    """Test suite for subagent status transitions, monotonicity, and watchdog anti-deadlock."""

    def test_valid_lifecycle_transitions(self) -> None:
        harmonizer = SubagentStatusHarmonizer(lease_timeout_seconds=20.0)
        agent_id = "worker-lifecycle-01"

        harmonizer.register_subagent(agent_id, initial_status=ToolReplayStatusEnum.IDLE)
        assert harmonizer.get_status(agent_id) == ToolReplayStatusEnum.IDLE

        # IDLE -> RUNNING
        ev1 = harmonizer.transition_status(agent_id, ToolReplayStatusEnum.RUNNING, reason="Started work")
        assert ev1.new_status == ToolReplayStatusEnum.RUNNING
        assert harmonizer.get_status(agent_id) == ToolReplayStatusEnum.RUNNING

        # RUNNING -> PENDING_APPROVAL
        ev2 = harmonizer.transition_status(agent_id, ToolReplayStatusEnum.PENDING_APPROVAL)
        assert ev2.new_status == ToolReplayStatusEnum.PENDING_APPROVAL

        # PENDING_APPROVAL -> RUNNING
        ev3 = harmonizer.transition_status(agent_id, ToolReplayStatusEnum.RUNNING, reason="Approved")
        assert ev3.new_status == ToolReplayStatusEnum.RUNNING

        # RUNNING -> COMPLETED
        ev4 = harmonizer.transition_status(agent_id, ToolReplayStatusEnum.COMPLETED)
        assert ev4.new_status == ToolReplayStatusEnum.COMPLETED
        assert harmonizer.get_status(agent_id) == ToolReplayStatusEnum.COMPLETED

    def test_invalid_transition_from_terminal_raises_error(self) -> None:
        harmonizer = SubagentStatusHarmonizer()
        agent_id = "worker-terminal-01"

        harmonizer.register_subagent(agent_id, initial_status=ToolReplayStatusEnum.RUNNING)
        harmonizer.transition_status(agent_id, ToolReplayStatusEnum.COMPLETED)

        # Attempt to revive or revert from terminal state
        with pytest.raises(ValueError, match="Cannot transition terminal subagent"):
            harmonizer.transition_status(agent_id, ToolReplayStatusEnum.RUNNING)

    def test_invalid_graph_jump_raises_error(self) -> None:
        harmonizer = SubagentStatusHarmonizer()
        agent_id = "worker-jump-01"

        harmonizer.register_subagent(agent_id, initial_status=ToolReplayStatusEnum.IDLE)

        # Direct IDLE -> COMPLETED is prohibited (must pass through RUNNING)
        with pytest.raises(ValueError, match="Invalid status transition"):
            harmonizer.transition_status(agent_id, ToolReplayStatusEnum.COMPLETED)

    def test_watchdog_auto_terminates_expired_leases(self) -> None:
        harmonizer = SubagentStatusHarmonizer(lease_timeout_seconds=10.0)
        agent_id = "worker-hung-01"
        t0 = 1000.0

        harmonizer.register_subagent(agent_id, initial_status=ToolReplayStatusEnum.IDLE)
        harmonizer.transition_status(agent_id, ToolReplayStatusEnum.RUNNING, now=t0)

        # At t0 + 5s (lease active, no timeout)
        interventions = harmonizer.check_watchdog(now=t0 + 5.0)
        assert len(interventions) == 0
        assert harmonizer.get_status(agent_id) == ToolReplayStatusEnum.RUNNING

        # Heartbeat refreshed at t0 + 8s
        assert harmonizer.record_heartbeat(agent_id, now=t0 + 8.0) is True

        # At t0 + 15s (7s after last heartbeat, within 10s lease)
        interventions = harmonizer.check_watchdog(now=t0 + 15.0)
        assert len(interventions) == 0

        # At t0 + 20s (12s after last heartbeat, lease exceeded!)
        interventions = harmonizer.check_watchdog(now=t0 + 20.0)
        assert len(interventions) == 1
        ev = interventions[0]
        assert ev.subagent_id == agent_id
        assert ev.previous_status == ToolReplayStatusEnum.RUNNING
        assert ev.new_status == ToolReplayStatusEnum.TIMEOUT_TERMINATED
        assert ev.is_deadlock_prevented is True
        assert harmonizer.get_status(agent_id) == ToolReplayStatusEnum.TIMEOUT_TERMINATED

        # Audit events contain the watchdog intervention
        audits = harmonizer.get_audit_events(subagent_id=agent_id)
        assert any(a.is_deadlock_prevented for a in audits)
