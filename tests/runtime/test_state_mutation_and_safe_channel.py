"""并发状态变异隔离与安全事件管道单元测试.

覆盖 Copy-on-Write 隔离、乐观并发冲突仲裁、管道三态生命周期、迟滞写入安全丢弃与上下文孤儿协程强杀回收.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.runtime.state_mutation_guard import (
    ChannelLifecycleState,
    ChannelPutResult,
    ChannelPutStatus,
    PatchConflictError,
    PatchConflictStrategy,
    SafeEventChannel,
    SessionStateMutator,
    TaskLifecycleScope,
)


def test_isolated_branch_view_cow() -> None:
    """验证分支隔离快照的 Copy-on-Write 行为，绝不提前污染宿主权威状态."""
    mutator = SessionStateMutator(
        session_id="test_sess_01",
        initial_data={"counter": 10, "status": "idle"},
    )
    branch = mutator.create_isolated_view("subagent_worker_1")

    # 分支修改本地视图
    branch.set("counter", 20)
    branch.set("new_flag", True)

    # 验证本地变更
    assert branch.get("counter") == 20
    assert branch.get("new_flag") is True

    # 验证宿主权威状态丝毫不受污染
    snapshot = mutator.get_snapshot()
    assert snapshot.data["counter"] == 10
    assert "new_flag" not in snapshot.data

    # 导出 Patch
    patch = branch.export_patch()
    assert patch.branch_id == "subagent_worker_1"
    assert patch.base_version == 1
    assert patch.mutations == {"counter": 20, "new_flag": True}

    # 合入 Patch
    res = mutator.commit_patch(patch)
    assert res.success is True
    assert res.resulting_version == 2
    assert set(res.applied_keys) == {"counter", "new_flag"}

    # 验证合入后的权威状态
    new_snapshot = mutator.get_snapshot()
    assert new_snapshot.version == 2
    assert new_snapshot.data["counter"] == 20
    assert new_snapshot.data["new_flag"] is True


def test_optimistic_concurrency_conflict_resolution() -> None:
    """验证多分支并发提交时的版本滞后检测与三种冲突仲裁策略."""
    mutator = SessionStateMutator(
        session_id="test_sess_02",
        initial_data={"config": {"retries": 3}, "step": "init"},
    )

    # 分支 A 与分支 B 在同一基础版本 v1 上派生
    branch_a = mutator.create_isolated_view("branch_a")
    branch_b = mutator.create_isolated_view("branch_b")

    branch_a.set("step", "step_a_done")
    branch_b.set("step", "step_b_done")

    # 分支 A 先合入，成功晋级到 v2
    patch_a = branch_a.export_patch()
    res_a = mutator.commit_patch(patch_a)
    assert res_a.resulting_version == 2

    patch_b = branch_b.export_patch()
    # 策略 1: FAIL_ON_CONFLICT，检测到 step 冲突，直接抛出强类型异常
    with pytest.raises(PatchConflictError) as exc_info:
        mutator.commit_patch(patch_b, strategy=PatchConflictStrategy.FAIL_ON_CONFLICT)
    assert "step" in exc_info.value.conflict_keys

    # 权威状态依然保持分支 A 的结果
    assert mutator.get_snapshot().data["step"] == "step_a_done"

    # 策略 2: LAST_WRITE_WINS，后写胜出，覆盖 step，并报告冲突键
    res_b = mutator.commit_patch(patch_b, strategy=PatchConflictStrategy.LAST_WRITE_WINS)
    assert res_b.success is True
    assert res_b.resulting_version == 3
    assert "step" in res_b.conflicted_keys
    assert mutator.get_snapshot().data["step"] == "step_b_done"

    # 策略 3: MERGE_DICT，嵌套字典递归合并
    branch_c = mutator.create_isolated_view("branch_c")
    branch_c.set("config", {"timeout": 30})
    patch_c = branch_c.export_patch()
    res_c = mutator.commit_patch(patch_c, strategy=PatchConflictStrategy.MERGE_DICT)
    assert res_c.success is True
    final_data = mutator.get_snapshot().data
    assert final_data["config"] == {"retries": 3, "timeout": 30}


@pytest.mark.asyncio
async def test_safe_event_channel_lifecycle_and_dropped_writes() -> None:
    """验证 SafeEventChannel 三态生命周期及主任务关闭后迟滞 safe_put 零崩溃丢弃."""
    chan: SafeEventChannel[str] = SafeEventChannel(channel_id="stream_chan_01")
    assert chan.state == ChannelLifecycleState.ACTIVE

    # 1. 正常投递与消费
    put_res1 = await chan.safe_put("msg_1")
    assert put_res1.status == ChannelPutStatus.DELIVERED
    assert chan.qsize == 1

    msg = await chan.get(timeout=0.5)
    assert msg == "msg_1"
    assert chan.consumed_count == 1

    # 2. 启动异步迟滞写入协程，尝试在管道关闭后写入
    async def delayed_writer() -> ChannelPutResult:
        await asyncio.sleep(0.05)
        # 此时主流程已关闭管道
        return await chan.safe_put("late_zombie_event")

    writer_task = asyncio.create_task(delayed_writer())

    # 3. 主流程平滑排空并关闭管道
    await chan.drain_and_close(timeout=0.5)
    assert chan.is_closed is True
    assert chan.state == ChannelLifecycleState.CLOSED

    # 4. 获取迟滞任务的结果，必须为安全丢弃，绝不抛出任何 send on closed channel 异常
    late_res = await writer_task
    assert late_res.status == ChannelPutStatus.DROPPED_CHANNEL_CLOSED
    assert chan.dropped_closed_count == 1

    # 关闭状态下读取直接返回 None
    assert await chan.get(timeout=0.1) is None


@pytest.mark.asyncio
async def test_safe_event_channel_queue_full_timeout() -> None:
    """验证有界队列满载超时时的安全丢弃机制，防止主流程与下游协程死锁."""
    chan: SafeEventChannel[int] = SafeEventChannel(channel_id="bounded_chan", maxsize=2)

    # 填满队列
    res1 = await chan.safe_put(101)
    res2 = await chan.safe_put(102)
    assert res1.status == ChannelPutStatus.DELIVERED
    assert res2.status == ChannelPutStatus.DELIVERED

    # 第 3 个元素在极短超时下由于队列满被安全丢弃
    res3 = await chan.safe_put(103, timeout=0.05)
    assert res3.status == ChannelPutStatus.DROPPED_QUEUE_FULL
    assert chan.dropped_full_count == 1
    assert "timeout" in (res3.dropped_reason or "").lower()

    # 立即关闭清理
    chan.close_immediate()
    assert chan.is_closed is True


@pytest.mark.asyncio
async def test_task_lifecycle_sentinel_orphan_reaping_and_closure() -> None:
    """验证 TaskLifecycleScope 退出时强制安全取消未决孤儿任务并自动关闭绑定管道."""
    chan: SafeEventChannel[str] = SafeEventChannel(channel_id="scope_bound_chan")
    worker_finished = False

    async def long_running_worker() -> None:
        nonlocal worker_finished
        try:
            while True:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            worker_finished = True
            raise

    # 场景 A: 正常退出上下文
    async with TaskLifecycleScope(scope_name="test_worker_scope") as scope:
        scope.bind_channel(chan)
        t = scope.spawn(long_running_worker(), name="eternal_worker")
        assert scope.active_tasks_count == 1
        assert not t.done()
        await asyncio.sleep(0.01)

    # 离开 Scope，任务应被强杀且捕获 CancelledError，管道应被关闭
    assert t.cancelled() is True
    assert worker_finished is True
    assert chan.is_closed is True

    # 场景 B: 主任务发生异常崩溃退出上下文
    chan2: SafeEventChannel[str] = SafeEventChannel(channel_id="crash_chan")
    orphan_killed = False

    async def orphan_worker() -> None:
        nonlocal orphan_killed
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            orphan_killed = True
            raise

    with pytest.raises(RuntimeError, match="Main process crashed"):
        async with TaskLifecycleScope(scope_name="crashing_scope") as scope2:
            scope2.bind_channel(chan2)
            scope2.spawn(orphan_worker())
            await asyncio.sleep(0.01)
            # 模拟业务崩溃
            raise RuntimeError("Main process crashed")

    # 验证异常崩溃下依然完成了 100% 任务清理与管道平稳关闭
    assert orphan_killed is True
    assert chan2.is_closed is True
