"""Five-Stage Clean Code Multi-Agent Assembly Pipeline Engine (Item 62).

[INPUT]
- CleanCodeTask specifications, stage artifact submissions, and module code maps.
- ArchitectureDependencyLinter for stage boundary gate checks.

[OUTPUT]
- CleanCodeTask state transitions across the 5 stages (Specifier -> Coder -> Cleaner -> Hardener -> QA).
- Gate-checked artifacts and pipeline completion records.

[POS]
- Harness orchestration engine eliminating LLM context degradation via 5 single-responsibility stages.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Final

from .arch_dependency_linter import ArchitectureDependencyLinter
from .types import (
    CleanCodeTask,
    LinterResult,
    PipelineStage,
    StageArtifact,
    StageStatus,
)

logger: Final = logging.getLogger(__name__)

# Ordered progression of stages
STAGE_ORDER: Final[list[PipelineStage]] = [
    PipelineStage.SPECIFIER,
    PipelineStage.CODER,
    PipelineStage.CLEANER,
    PipelineStage.HARDENER,
    PipelineStage.QA,
]


class CleanCodeAssemblyPipelineEngine:
    """Orchestrates five single-responsibility subagents in a clean code assembly line."""

    def __init__(self, linter: ArchitectureDependencyLinter | None = None) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, CleanCodeTask] = {}
        self._linter = linter if linter is not None else ArchitectureDependencyLinter()

    @property
    def linter(self) -> ArchitectureDependencyLinter:
        return self._linter

    def clear(self) -> None:
        """Reset all in-memory pipeline tasks."""
        with self._lock:
            self._tasks.clear()

    def start_pipeline(
        self,
        task_id: str,
        title: str,
        spec_prompt: str,
    ) -> CleanCodeTask:
        """Initialize a new Clean Code assembly pipeline run at SPECIFIER stage."""
        with self._lock:
            task = CleanCodeTask(
                task_id=task_id,
                title=title,
                spec_prompt=spec_prompt,
                current_stage=PipelineStage.SPECIFIER,
                status=StageStatus.RUNNING,
                artifacts={},
                stage_history=[PipelineStage.SPECIFIER.value],
                created_at=time.time(),
                updated_at=time.time(),
            )
            self._tasks[task_id] = task
            logger.info("Started Clean Code pipeline task %s ('%s')", task_id, title)
            return task

    def advance_stage(
        self,
        task_id: str,
        artifact_title: str,
        artifact_content: str,
        metadata: dict[str, str] | None = None,
    ) -> CleanCodeTask:
        """Submit the artifact for the current stage and advance to the next stage."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Clean Code task '{task_id}' not found")

            # 1. Store the artifact produced by the current stage
            current_stage = task.current_stage
            artifact = StageArtifact(
                stage=current_stage,
                title=artifact_title,
                content=artifact_content,
                metadata=dict(metadata) if metadata else {},
            )
            task.artifacts[current_stage.value] = artifact
            task.updated_at = time.time()

            # 2. Determine next stage in sequence
            current_idx = STAGE_ORDER.index(current_stage)
            if current_idx < len(STAGE_ORDER) - 1:
                next_stage = STAGE_ORDER[current_idx + 1]
                task.current_stage = next_stage
                task.status = StageStatus.RUNNING
                task.stage_history.append(next_stage.value)
                logger.info(
                    "Advanced pipeline task %s: %s -> %s",
                    task_id,
                    current_stage.value,
                    next_stage.value,
                )
            else:
                # All 5 stages completed (QA signed off)
                task.status = StageStatus.COMPLETED
                logger.info("Pipeline task %s successfully completed all 5 Clean Code stages", task_id)

            return task

    def lint_and_gate_check(
        self,
        task_id: str,
        module_code_map: dict[str, str],
    ) -> LinterResult:
        """Run architectural AST linter against pipeline code. Blocks task on inverted dependencies."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise KeyError(f"Clean Code task '{task_id}' not found")

            lint_result = self._linter.lint_project_modules(module_code_map)
            task.updated_at = time.time()

            if not lint_result.is_valid:
                # Found architectural violations; block pipeline until refactored
                task.status = StageStatus.BLOCKED
                task.artifacts["arch_lint_report"] = StageArtifact(
                    stage=task.current_stage,
                    title="Architecture Lint Gate Violations",
                    content=f"Detected {len(lint_result.violations)} layer violations.",
                    metadata={
                        "violations_count": str(len(lint_result.violations)),
                        "gate_status": "blocked",
                    },
                )
                logger.warning(
                    "Pipeline task %s BLOCKED by architecture linter with %d violations",
                    task_id,
                    len(lint_result.violations),
                )
            else:
                logger.info("Pipeline task %s passed architecture linter gate cleanly", task_id)

            return lint_result

    def get_task(self, task_id: str) -> CleanCodeTask | None:
        """Retrieve state of an individual pipeline task."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> list[CleanCodeTask]:
        """List all active or completed Clean Code assembly pipeline tasks."""
        with self._lock:
            return list(self._tasks.values())
