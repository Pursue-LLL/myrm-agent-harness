"""Unit tests for Hierarchical Context Timeout Tree and Cancel Propagation Suite."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from myrm_agent_harness.runtime.timeout_tree import (
    CancelReason,
    CascadeCancelSignal,
    TaskExecutionHandle,
    TimeoutLevel,
    TimeoutTreeNode,
    ZombieTaskReaper,
)


def test_strict_hierarchical_timeout_shrinkage() -> None:
    """Verify child timeouts are strictly contained and clamped by parent remaining deadlines."""
    gateway_node = TimeoutTreeNode(
        node_id="gw_1",
        level=TimeoutLevel.GATEWAY,
        timeout_s=5.0,
    )

    # Agent Context attempts to request 10.0s (greater than Gateway 5.0s)
    # Strict Invariant: Automatically clamped to <= Gateway's remaining time
    agent_node = gateway_node.create_child(
        node_id="agent_1",
        level=TimeoutLevel.AGENT_CONTEXT,
        requested_timeout_s=10.0,
        safety_buffer_s=0.5,
    )

    assert agent_node.timeout_s <= 4.5
    assert agent_node.remaining_time_s <= gateway_node.remaining_time_s


@pytest.mark.asyncio
async def test_cascade_cancel_propagation_tree() -> None:
    """Verify cancellation signal cascades down Gateway -> Context -> LLM -> Tool hierarchy."""
    gateway = TimeoutTreeNode("gw_root", TimeoutLevel.GATEWAY, timeout_s=60.0)
    agent_ctx = gateway.create_child("agent_loop", TimeoutLevel.AGENT_CONTEXT, requested_timeout_s=55.0)
    llm_call = agent_ctx.create_child("llm_infer", TimeoutLevel.LLM_CALL, requested_timeout_s=30.0)
    tool_exec = llm_call.create_child("tool_sandbox", TimeoutLevel.TOOL_EXEC, requested_timeout_s=10.0)

    hook_called = False

    def mock_kill_subprocess() -> None:
        nonlocal hook_called
        hook_called = True

    tool_exec.add_cancel_hook(mock_kill_subprocess)

    # Attach an active dummy background task to tool_exec
    async def dummy_hanging_task() -> None:
        await asyncio.sleep(100.0)

    task = asyncio.create_task(dummy_hanging_task())
    tool_exec.attach_task(task)

    # Trigger cancellation at root due to user disconnection
    signal = CascadeCancelSignal(
        source_level=TimeoutLevel.GATEWAY,
        reason=CancelReason.USER_DISCONNECT,
        details="Client closed browser tab",
    )
    await gateway.propagate_cancel(signal)

    # CRITICAL INVARIANT: All descendants must be marked cancelled immediately
    assert gateway.is_cancelled is True
    assert agent_ctx.is_cancelled is True
    assert llm_call.is_cancelled is True
    assert tool_exec.is_cancelled is True

    # Attached task must be cancelled
    assert task.cancelling() or task.cancelled() or task.done()

    # Cancel hook (killing sub-processes) must have executed
    assert hook_called is True

    # Clean up task
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_timeout_watchdog_automatic_cancellation() -> None:
    """Verify watchdog timer automatically propagates upstream timeout signal on deadline expiry."""
    gateway = TimeoutTreeNode("gw_short", TimeoutLevel.GATEWAY, timeout_s=0.05)
    child = gateway.create_child("child_tool", TimeoutLevel.TOOL_EXEC, requested_timeout_s=0.05)

    async with gateway:
        # Sleep past the 0.05s deadline
        await asyncio.sleep(0.08)

    # Watchdog should have triggered cancellation across the tree
    assert gateway.is_cancelled is True
    assert child.is_cancelled is True


@pytest.mark.asyncio
async def test_zombie_task_reaper_sweeping_and_markdown() -> None:
    """Verify zombie reaper terminates un-managed tasks and renders audit markdown."""
    reaper = ZombieTaskReaper(context_name="turn_audit_test")

    cleaned_task_ids: list[str] = []

    def make_cancel_hook(tid: str):
        def _hook() -> None:
            cleaned_task_ids.append(tid)

        return _hook

    # 1. Clean task: finishes normally and unregisters
    t1 = TaskExecutionHandle("task_clean", TimeoutLevel.TOOL_EXEC, "SearchDoc")
    reaper.register_task(t1)
    reaper.unregister_task("task_clean")

    # 2. Orphan task: stays active due to unexpected bug/hang
    t2 = TaskExecutionHandle(
        "task_orphan_zombie",
        TimeoutLevel.TOOL_EXEC,
        "HeavySandboxCode",
        cancel_hook=make_cancel_hook("task_orphan_zombie"),
    )
    reaper.register_task(t2)

    assert reaper.get_active_count() == 1

    # End of turn: Reaper sweeps all remaining tasks
    report = await reaper.reap_all_orphans()

    assert report.scanned_count == 1
    assert report.reaped_count == 1
    assert "task_orphan_zombie" in report.reaped_task_ids
    assert "task_orphan_zombie" in cleaned_task_ids
    assert reaper.get_active_count() == 0

    # Verify Markdown audit card rendering
    card = reaper.render_reaper_markdown(report)
    assert "### 🧟 零野生任务巡检与生命周期闭环看板" in card
    assert "task_orphan_zombie" in card
    assert "> [!WARNING]" in card
