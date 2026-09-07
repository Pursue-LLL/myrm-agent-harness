"""Agentic Codebase Slimming Pipeline coordinating concurrent subagents.

[INPUT]
- .types::DeadCodeCandidate, DeadCodeScanReport, SlimmingLedger, SlimmingModuleTask, SlimmingTaskStatus (POS: Data models)
- .scanner::DeadCodeTopologyScanner (POS: Static analyzer)
- .guard::EquivalenceInvarianceGuard (POS: Regression testing assertion)
- ..workspace_isolation::isolated_workspace (POS: Isolated workspace sandbox)

[OUTPUT]
- CodebaseSlimmingPipeline: Main orchestrator executing wave-based slimming subagents with rollback protection.

[POS]
Orchestration engine coordinating distributed refactoring waves and merging verified changes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from myrm_agent_harness.agent.sub_agents.codebase_slimming.guard import (
    EquivalenceInvarianceGuard,
)
from myrm_agent_harness.agent.sub_agents.codebase_slimming.scanner import (
    DeadCodeTopologyScanner,
)
from myrm_agent_harness.agent.sub_agents.codebase_slimming.types import (
    DeadCodeCandidate,
    DeadCodeScanReport,
    SlimmingLedger,
    SlimmingModuleTask,
    SlimmingTaskStatus,
)
from myrm_agent_harness.agent.sub_agents.workspace_isolation import isolated_workspace
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class CodebaseSlimmingPipeline:
    """Coordinates scan, isolated wave execution, equivalence testing, and ledger output."""

    def __init__(
        self,
        workspace_dir: Path | str,
        test_command: str = "pytest",
        max_concurrent_workers: int = 4,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).resolve()
        self.test_command = test_command
        self.semaphore = asyncio.Semaphore(max(1, max_concurrent_workers))

    def scan(self) -> DeadCodeScanReport:
        """Scan workspace and generate dead code candidate report."""
        return DeadCodeTopologyScanner.scan_workspace(self.workspace_dir)

    def group_tasks_by_file(
        self, report: DeadCodeScanReport
    ) -> list[SlimmingModuleTask]:
        """Group candidates into discrete file/module tasks."""
        by_file: dict[str, list[DeadCodeCandidate]] = {}
        for c in report.candidates:
            by_file.setdefault(c.file_path, []).append(c)

        tasks: list[SlimmingModuleTask] = []
        for idx, (fpath, cands) in enumerate(by_file.items(), start=1):
            tasks.append(
                SlimmingModuleTask(
                    task_id=f"slimming_task_{idx:03d}",
                    module_path=fpath,
                    candidates=tuple(cands),
                    test_command=self.test_command,
                )
            )
        return tasks

    async def execute_task_with_worker(
        self,
        task: SlimmingModuleTask,
        worker_fn: Callable[[Path, SlimmingModuleTask], Coroutine[Any, Any, int]],
    ) -> tuple[SlimmingModuleTask, bool]:
        """Execute a single module refactoring in an isolated workspace copy.
        
        If worker_fn or regression tests fail, changes are cleanly discarded (rollback).
        """
        async with self.semaphore:
            target_file = self.workspace_dir / task.module_path
            if not target_file.exists():
                return (
                    SlimmingModuleTask(
                        task_id=task.task_id,
                        module_path=task.module_path,
                        candidates=task.candidates,
                        status=SlimmingTaskStatus.FAILED,
                        error_message="Target module not found",
                    ),
                    False,
                )

            # 1. Execute inside isolated clone
            try:
                async with isolated_workspace(self.workspace_dir) as iso_dir:
                    # Run custom worker (e.g. LLM or deterministic AST remover)
                    lines_cut = await worker_fn(iso_dir, task)

                    # 2. Test equivalence invariance before sync back
                    verdict = await EquivalenceInvarianceGuard.assert_invariance(
                        iso_dir, test_command=task.test_command
                    )

                    if not verdict.passed:
                        logger.warning(
                            "Slimming task %s failed equivalence tests: %s. Rolling back.",
                            task.task_id,
                            verdict.failure_reason,
                        )
                        return (
                            SlimmingModuleTask(
                                task_id=task.task_id,
                                module_path=task.module_path,
                                candidates=task.candidates,
                                status=SlimmingTaskStatus.ROLLED_BACK,
                                error_message=verdict.failure_reason,
                            ),
                            False,
                        )

                    # 3. If passed, apply changes to live workspace directly
                    iso_target = iso_dir / task.module_path
                    if iso_target.exists():
                        target_file.write_text(
                            iso_target.read_text(encoding="utf-8"), encoding="utf-8"
                        )

                    return (
                        SlimmingModuleTask(
                            task_id=task.task_id,
                            module_path=task.module_path,
                            candidates=task.candidates,
                            status=SlimmingTaskStatus.PASSED,
                            actual_lines_cut=lines_cut,
                        ),
                        True,
                    )
            except Exception as exc:
                logger.error("Slimming task %s crashed: %s", task.task_id, exc)
                return (
                    SlimmingModuleTask(
                        task_id=task.task_id,
                        module_path=task.module_path,
                        candidates=task.candidates,
                        status=SlimmingTaskStatus.FAILED,
                        error_message=str(exc),
                    ),
                    False,
                )

    async def run_pipeline(
        self,
        worker_fn: Callable[[Path, SlimmingModuleTask], Coroutine[Any, Any, int]],
    ) -> tuple[SlimmingLedger, list[SlimmingModuleTask]]:
        """Run full scanning, concurrent execution waves, and compile accounting ledger."""
        start_time = time.time()
        report = self.scan()
        tasks = self.group_tasks_by_file(report)

        if not tasks:
            return SlimmingLedger(duration_seconds=time.time() - start_time), []

        # Execute concurrent waves
        results = await asyncio.gather(
            *[self.execute_task_with_worker(t, worker_fn) for t in tasks]
        )

        completed_tasks: list[SlimmingModuleTask] = []
        total_lines_cut = 0
        success_count = 0
        rollback_count = 0

        for updated_task, passed in results:
            completed_tasks.append(updated_task)
            if passed:
                success_count += 1
                total_lines_cut += updated_task.actual_lines_cut
            elif updated_task.status == SlimmingTaskStatus.ROLLED_BACK:
                rollback_count += 1

        elapsed = time.time() - start_time
        ledger = SlimmingLedger(
            total_tasks=len(tasks),
            successful_tasks=success_count,
            rolled_back_tasks=rollback_count,
            lines_cut=total_lines_cut,
            estimated_token_context_saved=total_lines_cut * 12,  # ~12 tokens per line
            duration_seconds=elapsed,
        )

        return ledger, completed_tasks
