"""Unlocked Parallel Multiplexer for Heterogeneous External Subagents.

[INPUT]
- __future__
- asyncio
- re
- time
- uuid
- collections

[OUTPUT]
- ConcurrencyLimitExceededError
- ExternalSubagentMultiplexer

[POS]
Unlocked Parallel Multiplexer for Heterogeneous External Subagents.

"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Callable, Coroutine

from .bundle_registry import (
    ExternalAgentBundleRegistry,
)
from .types import (
    BatchDispatchResult,
    BatchDispatchTask,
    SubagentInstanceRecord,
    SubagentInstanceStatusEnum,
)


class ConcurrencyLimitExceededError(Exception):
    """Raised when active instances for a bundle exceed max_concurrency."""


class ExternalSubagentMultiplexer:
    """Orchestrates non-blocking parallel execution of heterogeneous third-party agents

    eliminating per-backend mutex bottlenecks and reshaping output into unified event streams.
    """

    def __init__(self, registry: ExternalAgentBundleRegistry | None = None) -> None:
        self.registry = registry or ExternalAgentBundleRegistry()
        # instance_id -> SubagentInstanceRecord
        self._instances: dict[str, SubagentInstanceRecord] = {}
        # instance_id -> asyncio.Task
        self._active_tasks: dict[str, asyncio.Task[None]] = {}

    def get_instance(self, instance_id: str) -> SubagentInstanceRecord | None:
        """Fetch instance record by ID."""
        return self._instances.get(instance_id)

    def list_instances(self, session_id: str | None = None) -> list[SubagentInstanceRecord]:
        """List instance records, optionally filtered by session_id."""
        if session_id:
            return [inst for inst in self._instances.values() if inst.session_id == session_id]
        return list(self._instances.values())

    def count_active_instances(self, bundle_id: str) -> int:
        """Count active running instances for a specific bundle."""
        return sum(
            1
            for inst in self._instances.values()
            if inst.bundle_id == bundle_id and inst.status in {SubagentInstanceStatusEnum.RUNNING, SubagentInstanceStatusEnum.PENDING}
        )

    def dispatch_instance(
        self,
        session_id: str,
        task: BatchDispatchTask,
        workspace_root: str,
        custom_executor: Callable[[SubagentInstanceRecord], Coroutine[None, None, None]] | None = None,
    ) -> SubagentInstanceRecord:
        """Dispatch a single external subagent instance without holding global backend locks."""
        bundle = self.registry.get_bundle(task.bundle_id)

        # 1. Enforce sandbox directory boundary
        target_workdir = workspace_root
        if task.target_subdir:
            target_workdir = f"{workspace_root}/{task.target_subdir.strip('/')}"
        safe_workdir = self.registry.validate_directory_boundary(
            bundle_id=task.bundle_id,
            target_path=target_workdir,
            session_workspace_root=workspace_root,
        )

        # 2. Check per-bundle concurrency limit (NO global mutex!)
        active_count = self.count_active_instances(task.bundle_id)
        if active_count >= bundle.max_concurrency:
            raise ConcurrencyLimitExceededError(
                f"Bundle '{bundle.bundle_id}' reached max concurrency of {bundle.max_concurrency} (active: {active_count})."
            )

        # 3. Create instance record
        instance_id = f"inst-{bundle.bundle_id}-{task.role_label}-{uuid.uuid4().hex[:6]}"
        record = SubagentInstanceRecord(
            instance_id=instance_id,
            bundle_id=task.bundle_id,
            session_id=session_id,
            role_label=task.role_label,
            status=SubagentInstanceStatusEnum.PENDING,
            task_prompt=task.task_prompt,
            target_workdir=safe_workdir,
            created_at=time.time(),
        )
        self._instances[instance_id] = record

        # 4. Launch asynchronous execution task
        executor = custom_executor or self._default_mock_executor
        coro = self._run_instance_wrapper(record, task.timeout_seconds, executor)
        try:
            loop = asyncio.get_running_loop()
            async_task = loop.create_task(coro)
            self._active_tasks[instance_id] = async_task
        except RuntimeError:
            # When called in sync context or before loop is running
            pass

        return record

    async def dispatch_batch(
        self,
        session_id: str,
        tasks: list[BatchDispatchTask],
        workspace_root: str,
        custom_executor: Callable[[SubagentInstanceRecord], Coroutine[None, None, None]] | None = None,
    ) -> BatchDispatchResult:
        """Concurrently dispatch multiple external subagent instances (e.g. 2 Codex + 1 Claude Code)."""
        batch_id = f"batch-{uuid.uuid4().hex[:8]}"
        dispatched: list[SubagentInstanceRecord] = []

        for task in tasks:
            record = self.dispatch_instance(
                session_id=session_id,
                task=task,
                workspace_root=workspace_root,
                custom_executor=custom_executor,
            )
            dispatched.append(record)

        return BatchDispatchResult(
            batch_id=batch_id,
            session_id=session_id,
            total_dispatched=len(dispatched),
            dispatched_instances=dispatched,
        )

    def terminate_instance(self, instance_id: str, reason: str = "manual_kill") -> bool:
        """Terminate a running instance and mark status as TERMINATED."""
        record = self._instances.get(instance_id)
        if not record:
            return False

        if record.status in {SubagentInstanceStatusEnum.COMPLETED, SubagentInstanceStatusEnum.FAILED, SubagentInstanceStatusEnum.TERMINATED}:
            return False

        if instance_id in self._active_tasks:
            task = self._active_tasks.pop(instance_id)
            task.cancel()

        record.status = SubagentInstanceStatusEnum.TERMINATED
        record.completed_at = time.time()
        record.error = f"Terminated: {reason}"
        return True

    def reshape_and_append_stdout(self, record: SubagentInstanceRecord, raw_line: str) -> None:
        """Normalize terminal output, strip ANSI sequences, and extract structured artifacts."""
        # Strip ANSI escape codes
        ansi_regex = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        cleaned_line = ansi_regex.sub("", raw_line).strip()
        if not cleaned_line:
            return

        record.stdout_chunks.append(cleaned_line)

        # Artifact extraction heuristic: [artifact:diff:path.py] or [artifact:result]
        diff_match = re.search(r"\[artifact:diff:(?P<path>[^\]]+)\]\s*(?P<diff>.*)", cleaned_line)
        if diff_match:
            record.artifacts.append({
                "type": "diff",
                "path": diff_match.group("path"),
                "content": diff_match.group("diff"),
            })
            return

        res_match = re.search(r"\[artifact:result\]\s*(?P<content>.*)", cleaned_line)
        if res_match:
            record.artifacts.append({
                "type": "result_summary",
                "content": res_match.group("content"),
            })

    async def _run_instance_wrapper(
        self,
        record: SubagentInstanceRecord,
        timeout: float,
        executor: Callable[[SubagentInstanceRecord], Coroutine[None, None, None]],
    ) -> None:
        """Wrapper handling instance lifecycle transitions, timeout, and exception capture."""
        record.status = SubagentInstanceStatusEnum.RUNNING
        record.started_at = time.time()

        try:
            await asyncio.wait_for(executor(record), timeout=timeout)
            record.status = SubagentInstanceStatusEnum.COMPLETED
            record.exit_code = 0
        except TimeoutError:
            record.status = SubagentInstanceStatusEnum.FAILED
            record.error = f"Execution timed out after {timeout} seconds."
            record.exit_code = 124
        except asyncio.CancelledError:
            record.status = SubagentInstanceStatusEnum.TERMINATED
            record.error = "Instance execution cancelled."
            record.exit_code = 130
        except Exception as exc:
            record.status = SubagentInstanceStatusEnum.FAILED
            record.error = str(exc)
            record.exit_code = 1
        finally:
            record.completed_at = time.time()
            self._active_tasks.pop(record.instance_id, None)

    async def _default_mock_executor(self, record: SubagentInstanceRecord) -> None:
        """Simulate realistic external CLI processing without spawning unmocked child processes."""
        await asyncio.sleep(0.05)
        self.reshape_and_append_stdout(record, f"\x1b[32m[INFO]\x1b[0m {record.bundle_id} initialized in {record.target_workdir}")
        self.reshape_and_append_stdout(record, f"Processing role task: {record.role_label}")
        self.reshape_and_append_stdout(record, f"[artifact:diff:{record.role_label}.ts] +export const ready = true;")
        self.reshape_and_append_stdout(record, f"[artifact:result] Task completed successfully for {record.role_label}.")
