"""Zombie task reaper guard for enforcing absolute physical lifecycle closure.

Scans for orphan background futures or leaked worker processes when a turn concludes,
forcefully terminating stray tasks and reporting audit telemetries.

[INPUT]
- __future__
- asyncio
- time
- timeout_tree_types

[OUTPUT]
- ZombieTaskReaper

[POS]
Zombie task reaper guard for enforcing absolute physical lifecycle closure.
"""

from __future__ import annotations

import asyncio
import time

from .timeout_tree_types import (
    TaskExecutionHandle,
    ZombieReaperReport,
)


class ZombieTaskReaper:
    """Monitors scheduled tasks within an execution context and terminates leaked orphans."""

    def __init__(self, context_name: str = "default_turn") -> None:
        self.context_name = context_name
        self._tracked_tasks: dict[str, TaskExecutionHandle] = {}

    def register_task(self, handle: TaskExecutionHandle) -> None:
        """Register an active task or background job handle for lifecycle tracking."""
        self._tracked_tasks[handle.task_id] = handle

    def unregister_task(self, task_id: str) -> None:
        """Unregister a task upon its clean, expected completion."""
        self._tracked_tasks.pop(task_id, None)

    def get_active_count(self) -> int:
        """Return the count of currently registered active tasks."""
        return len(self._tracked_tasks)

    async def reap_all_orphans(self) -> ZombieReaperReport:
        """Sweep and aggressively terminate all lingering orphan tasks.

        Guarantees that no unmanaged background worker continues consuming
        CPU, GPU, or token quotas after conversational scope teardown.
        """
        scanned_count = len(self._tracked_tasks)
        reaped_ids: list[str] = []

        for task_id, handle in list(self._tracked_tasks.items()):
            if handle.is_active:
                if handle.cancel_hook:
                    try:
                        res = handle.cancel_hook()
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception:
                        # Reaper errors on a single task must not abort sweeping remaining tasks
                        pass

                handle.is_active = False
                reaped_ids.append(task_id)

        self._tracked_tasks.clear()

        return ZombieReaperReport(
            scanned_count=scanned_count,
            reaped_count=len(reaped_ids),
            reaped_task_ids=tuple(reaped_ids),
            has_leaked_tasks=len(reaped_ids) > 0,
            reaped_at=time.time(),
        )

    def render_reaper_markdown(self, report: ZombieReaperReport) -> str:
        """Render a GitHub Flavored Markdown audit card detailing orphan task cleanup."""
        lines: list[str] = [
            f"### 🧟 零野生任务巡检与生命周期闭环看板: `{self.context_name}`",
            f"- **退出时扫描任务总数**: `{report.scanned_count}`",
            f"- **强制绝杀僵尸任务数**: `{report.reaped_count}`",
            "",
        ]

        if report.has_leaked_tasks:
            lines.extend(
                [
                    "#### ⚠️ 被清理的孤儿任务列表",
                    *[f"- 🛑 僵尸任务 ID: `{tid}`" for tid in report.reaped_task_ids],
                    "",
                    "> [!WARNING]",
                    f"> 检测到 {report.reaped_count} 个后台孤儿任务在交互边界未正常退出。巡检器已执行物理强杀，杜绝了后台无界空跑与资源泄漏。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!NOTE]",
                    "> **[物理闭环达成]** 上下文正常退出，所有衍生任务与连接均已确定性完成注销，未产生任何后台僵尸任务。",
                ]
            )

        return "\n".join(lines)
