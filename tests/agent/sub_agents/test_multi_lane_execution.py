"""Unit tests for Pi Harness v2 multi-lane parallel thread execution."""

import asyncio

import pytest

from myrm_agent_harness.agent.sub_agents.multi_lane import (
    LaneConcurrencyConflictError,
    LaneNotFoundError,
    LaneState,
    MultiLaneSessionCoordinator,
    NodeNotFoundError,
    OperationNotFoundError,
    OpStatus,
)


@pytest.mark.asyncio
async def test_default_session_initialization() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-init-01")
    snapshot = await coordinator.get_snapshot()

    assert snapshot.session_id == "session-init-01"
    assert snapshot.total_nodes == 1  # root node
    assert snapshot.active_lanes_count == 0
    assert "main" in snapshot.lanes

    main_lane = snapshot.lanes["main"]
    assert main_lane.lane_id == "main"
    assert main_lane.state == LaneState.IDLE
    assert main_lane.current_leaf_id == "root"
    assert main_lane.active_op_id is None
    assert main_lane.total_ops == 0


@pytest.mark.asyncio
async def test_create_custom_lanes_with_fork() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-fork-02")

    # Append a node to main
    root_node = await coordinator.append_node(
        lane_id="main",
        content="Parent conversation message",
        node_type="message",
    )

    # Fork thread-1 from main's leaf
    thread_1 = await coordinator.create_lane(
        lane_id="slack:thread-101",
        display_name="Slack Thread #101",
        fork_from_node_id=root_node.node_id,
    )
    assert thread_1.lane_id == "slack:thread-101"
    assert thread_1.current_leaf_id == root_node.node_id
    assert thread_1.state == LaneState.IDLE

    # Calling create_lane with existing id is idempotent
    existing = await coordinator.create_lane(
        lane_id="slack:thread-101",
        display_name="Slack Thread #101 Dup",
    )
    assert existing.lane_id == "slack:thread-101"

    # Forking from non-existent node raises error
    with pytest.raises(NodeNotFoundError):
        await coordinator.create_lane(
            lane_id="invalid-lane",
            display_name="Invalid Fork",
            fork_from_node_id="non-existent-node-id",
        )


@pytest.mark.asyncio
async def test_single_lane_concurrency_conflict_enforced() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-conflict-03")

    # Dispatch first operation on main
    op1 = await coordinator.dispatch_operation(
        lane_id="main",
        name="run_heavy_analysis",
        payload={"param": "value1"},
    )
    assert op1.status == OpStatus.RUNNING
    main_info = await coordinator.get_lane("main")
    assert main_info.state == LaneState.RUNNING
    assert main_info.active_op_id == op1.op_id

    # Attempting second operation on same lane MUST raise LaneConcurrencyConflictError
    with pytest.raises(LaneConcurrencyConflictError) as exc_info:
        await coordinator.dispatch_operation(
            lane_id="main",
            name="run_second_operation",
        )
    assert "Per-lane concurrency constraint" in str(exc_info.value)


@pytest.mark.asyncio
async def test_multi_lane_parallel_operations_run_concurrently() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-parallel-04")

    # Create two additional lanes
    await coordinator.create_lane("thread:review-1", "Code Review Thread")
    await coordinator.create_lane("thread:test-2", "Test Execution Thread")

    # Concurrently dispatch operations on different lanes
    op_main = await coordinator.dispatch_operation("main", "main_task")
    op_rev = await coordinator.dispatch_operation("thread:review-1", "review_task")
    op_tst = await coordinator.dispatch_operation("thread:test-2", "test_task")

    snapshot = await coordinator.get_snapshot()
    assert snapshot.active_lanes_count == 3
    assert snapshot.lanes["main"].state == LaneState.RUNNING
    assert snapshot.lanes["thread:review-1"].state == LaneState.RUNNING
    assert snapshot.lanes["thread:test-2"].state == LaneState.RUNNING

    # Complete them in parallel
    async def finish_op(lane: str, op_id: str, res: str) -> None:
        await asyncio.sleep(0.01)
        await coordinator.complete_operation(lane, op_id, result_content=res)

    await asyncio.gather(
        finish_op("main", op_main.op_id, "Main done"),
        finish_op("thread:review-1", op_rev.op_id, "Review done"),
        finish_op("thread:test-2", op_tst.op_id, "Test done"),
    )

    final_snapshot = await coordinator.get_snapshot()
    assert final_snapshot.active_lanes_count == 0
    assert final_snapshot.total_nodes == 4  # 1 root + 3 result nodes


@pytest.mark.asyncio
async def test_operation_lifecycle_success_and_node_append() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-lifecycle-05")

    op = await coordinator.dispatch_operation("main", "compute_metrics")
    completed = await coordinator.complete_operation(
        lane_id="main",
        op_id=op.op_id,
        result_content="Metrics computation output: 42",
    )

    assert completed.status == OpStatus.COMPLETED
    assert completed.completed_at is not None
    assert completed.result_node_id is not None

    main_lane = await coordinator.get_lane("main")
    assert main_lane.state == LaneState.IDLE
    assert main_lane.active_op_id is None
    assert main_lane.current_leaf_id == completed.result_node_id

    # Check op log
    log = await coordinator.get_op_log("main")
    assert len(log) == 1
    assert log[0].op_id == op.op_id
    assert log[0].status == OpStatus.COMPLETED


@pytest.mark.asyncio
async def test_operation_failure_and_cancellation() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-fail-cancel-06")

    # Test failure
    op_fail = await coordinator.dispatch_operation("main", "flaky_task")
    failed = await coordinator.complete_operation(
        lane_id="main",
        op_id=op_fail.op_id,
        error="Connection timeout during network fetch",
    )
    assert failed.status == OpStatus.FAILED
    assert failed.error_message == "Connection timeout during network fetch"
    assert (await coordinator.get_lane("main")).state == LaneState.IDLE

    # Test cancellation
    op_cancel = await coordinator.dispatch_operation("main", "cancelled_task")
    cancelled = await coordinator.cancel_operation(
        lane_id="main",
        op_id=op_cancel.op_id,
        reason="User aborted thread",
    )
    assert cancelled.status == OpStatus.CANCELLED
    assert cancelled.error_message == "User aborted thread"
    assert (await coordinator.get_lane("main")).state == LaneState.IDLE


@pytest.mark.asyncio
async def test_error_cases_invalid_lanes_and_ops() -> None:
    coordinator = MultiLaneSessionCoordinator(session_id="session-errors-07")

    with pytest.raises(LaneNotFoundError):
        await coordinator.dispatch_operation("ghost-lane", "any_op")

    with pytest.raises(LaneNotFoundError):
        await coordinator.get_lane("ghost-lane")

    with pytest.raises(LaneNotFoundError):
        await coordinator.get_op_log("ghost-lane")

    with pytest.raises(OperationNotFoundError):
        await coordinator.complete_operation("main", "non-existent-op")

    with pytest.raises(OperationNotFoundError):
        await coordinator.cancel_operation("main", "non-existent-op")
