"""Zombie cleanup supervisor and tiered progressive timeout watchdog for subagents.

Benchmarked against Nous community multi-agent runtime reliability invariants:
- Supervises subagent execution through an active heartbeat monitor.
- Applies progressive timeout ladder: Warning -> Soft Cancel -> Hard Terminate.
- Physically terminates unresponsive zombie workers via cleanup hooks.
- Produces structured execution receipts for parent agents to enable graceful degradation.

[OUTPUT]
- ZombieCleanupSupervisor: Supervises subagent coroutines and reaps unresponsive zombie tasks.

[INPUT]
- __future__
- asyncio
- contextlib
- time
- collections

[OUTPUT]
- ZombieCleanupSupervisor

[POS]
Zombie cleanup supervisor and tiered progressive timeout watchdog for subagents.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Coroutine

from myrm_agent_harness.runtime.subagent_watchdog.subagent_heartbeat_tracker import (
    SubagentHeartbeatTracker,
)
from myrm_agent_harness.runtime.subagent_watchdog.watchdog_types import (
    SubagentExecutionReceipt,
    SubagentHealthState,
    TimeoutLadderConfig,
)


class ZombieCleanupSupervisor:
    """Supervises subagent tasks and reaps unresponsive zombie workers to prevent parent hangs."""

    def __init__(self, tracker: SubagentHeartbeatTracker | None = None) -> None:
        self.tracker = tracker or SubagentHeartbeatTracker()

    async def supervise_task(
        self,
        subagent_id: str,
        parent_session_id: str,
        coro: Coroutine[object, object, str],
        cleanup_hook: Callable[[], None] | None = None,
        custom_ladder: TimeoutLadderConfig | None = None,
        check_interval_s: float = 0.05,
    ) -> tuple[SubagentHealthState, str, SubagentExecutionReceipt]:
        """Supervise an asynchronous subagent task against progressive timeout thresholds.

        Args:
            subagent_id: Identifier of the monitored subagent.
            parent_session_id: ID of the parent session that spawned the subagent.
            coro: Asynchronous coroutine performing the subagent's workload.
            cleanup_hook: Optional callable to forcibly kill background subprocesses or clean mounts.
            custom_ladder: Custom timeout thresholds for this specific task.
            check_interval_s: Polling interval for heartbeat health evaluation.

        Returns:
            Tuple of (final_health_state, result_payload, SubagentExecutionReceipt).
        """
        active_ladder = custom_ladder or self.tracker.default_ladder
        self.tracker.register(subagent_id, active_ladder)
        start_time = time.time()
        zombie_killed = False

        task = asyncio.create_task(coro)

        try:
            while not task.done():
                await asyncio.sleep(check_interval_s)
                health, _ = self.tracker.evaluate_health(subagent_id)

                if health == SubagentHealthState.SOFT_CANCELING and not task.cancelling():
                    # Attempt gentle cooperative cancellation
                    task.cancel()

                if health == SubagentHealthState.TERMINATED:
                    # Hard deadline passed: task is an uncooperative zombie
                    if not task.done():
                        task.cancel()
                    if cleanup_hook is not None:
                        with contextlib.suppress(Exception):
                            cleanup_hook()
                    zombie_killed = True
                    break

            if zombie_killed:
                final_state = SubagentHealthState.TERMINATED
                result = ""
                err_summary = (
                    f"Subagent '{subagent_id}' became an unresponsive zombie (no heartbeat for "
                    f"{active_ladder.hard_terminate_threshold_s}s); forcibly terminated by watchdog."
                )
            elif task.cancelled():
                final_state = SubagentHealthState.SOFT_CANCELING
                result = ""
                err_summary = f"Subagent '{subagent_id}' was cancelled due to heartbeat warning/timeout."
            elif task.exception() is not None:
                final_state = SubagentHealthState.TERMINATED
                result = ""
                err_summary = f"Subagent '{subagent_id}' failed with exception: {task.exception()}"
            else:
                final_state = SubagentHealthState.HEALTHY
                result = task.result()
                err_summary = ""

        finally:
            total_pulses = self.tracker.get_pulse_count(subagent_id)
            self.tracker.unregister(subagent_id)

        elapsed_total = round(time.time() - start_time, 3)

        receipt = SubagentExecutionReceipt(
            subagent_id=subagent_id,
            parent_session_id=parent_session_id,
            final_state=final_state,
            total_pulses=total_pulses,
            elapsed_seconds=elapsed_total,
            zombie_killed=zombie_killed,
            degraded_error_summary=err_summary,
        )

        return final_state, result, receipt

    @staticmethod
    def render_watchdog_markdown(receipt: SubagentExecutionReceipt) -> str:
        """Render a GitHub Flavored Markdown card summarizing subagent watchdog execution."""
        lines: list[str] = [
            "### 🛡️ 子智能体心跳看门狗与僵尸清退审计卡片",
            f"- **子智能体 ID**: `{receipt.subagent_id}`",
            f"- **所属父会话**: `{receipt.parent_session_id}`",
            f"- **最终健康状态**: `{receipt.final_state.value.upper()}`",
            f"- **累计心跳脉冲**: `{receipt.total_pulses}`",
            f"- **总执行耗时**: `{receipt.elapsed_seconds}s`",
            f"- **是否物理清理僵尸进程**: `{'⚠️ 是 (已强杀)' if receipt.zombie_killed else '否'}`",
            "",
        ]

        if receipt.final_state == SubagentHealthState.HEALTHY:
            lines.extend(
                [
                    "> [!NOTE]",
                    "> 子智能体在执行周期内心跳正常，工作负载顺利完成，未发生超时阻塞。",
                ]
            )
        elif receipt.final_state == SubagentHealthState.TERMINATED:
            lines.extend(
                [
                    "> [!CAUTION]",
                    f"> **子智能体僵尸硬清退告警**：{receipt.degraded_error_summary}",
                    "> 父会话已启动优雅降级，防止主调度器无限期挂起死等。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> **子智能体执行异常**：{receipt.degraded_error_summary}",
                ]
            )

        return "\n".join(lines)
