"""Subagent cancel, steer, list, and wait operations.

[INPUT]
- manager::SubagentManager (POS: Access to internal state via self reference)
- types::SubAgentStatus, CancellationStrategy, SubagentConfig

[OUTPUT]
- SubagentControlMixin: Mixin providing cancel_child, cancel_all, steer_child,
  list_children, wait_children, drain_notifications, run_chain, run_with_verification

[POS]
Control plane operations for SubagentManager.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.sub_agents.types import (
    CancellationStrategy,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.sub_agents.manager import SubagentTask

logger = logging.getLogger(__name__)


class SubagentControlMixin:
    """Cancel, steer, list, wait, chain, verify, and drain operations for SubagentManager."""

    _children: dict[str, SubagentTask]
    _children_types: dict[str, str]
    _children_descriptions: dict[str, str]
    _children_configs: dict[str, SubagentConfig]
    _children_results: dict[str, SubAgentResult]
    _children_steering: dict[str, object]
    _cancel_flags: dict[str, bool]
    _graceful_cancel_timeouts: dict[str, asyncio.Task[None]]
    _background_tasks: set[asyncio.Task[object]]
    _children_agents: dict[str, object]

    def list_children(self) -> list[dict[str, object]]:
        children: list[dict[str, object]] = []

        for task_id, task in self._children.items():
            metadata = self._child_observability_metadata(task_id)  # type: ignore[attr-defined]
            children.append(
                {
                    "task_id": task_id,
                    "agent_type": self._children_types.get(task_id, "unknown"),
                    "description": self._children_descriptions.get(task_id, ""),
                    "status": SubAgentStatus.RUNNING.value,
                    "done": task.done(),
                    "cancelled": task.cancelled(),
                    **metadata,
                }
            )

        for task_id, result in self._children_results.items():
            children.append(
                {
                    **result.to_dict(),
                    **self._child_observability_metadata(task_id),  # type: ignore[attr-defined]
                }
            )

        return children

    async def _graceful_cancel_timeout_handler(self, task_id: str, task: SubagentTask, timeout_seconds: float) -> None:
        """Force-cancel if graceful cancellation exceeds timeout."""
        try:
            await asyncio.sleep(timeout_seconds)
            if not task.done():
                logger.warning(
                    "[subagent:%s] Graceful cancellation timeout (%.0fs), forcing immediate cancellation",
                    task_id,
                    timeout_seconds,
                )
                task.cancel()
        except asyncio.CancelledError:
            pass

    def cancel_child(self, task_id: str) -> bool:
        task = self._children.get(task_id)
        if task is None:
            logger.warning("Cannot cancel task %s: not found in running tasks", task_id)
            return False
        if task.done():
            logger.warning("Cannot cancel task %s: already done", task_id)
            return False

        config = self._children_configs.get(task_id)
        if config is None:
            task.cancel()
            logger.info("[subagent:%s] Cancelled (no config, using IMMEDIATE)", task_id)
            return True

        strategy = config.cancellation_strategy

        if strategy == CancellationStrategy.IMMEDIATE:
            task.cancel()
            logger.info("[subagent:%s] Cancelled (IMMEDIATE)", task_id)
        elif strategy == CancellationStrategy.GRACEFUL:
            self._cancel_flags[task_id] = True
            logger.info("[subagent:%s] Cancel flag set (GRACEFUL)", task_id)
            timeout_task = asyncio.create_task(
                self._graceful_cancel_timeout_handler(task_id, task, config.graceful_cancel_timeout_seconds)
            )
            self._graceful_cancel_timeouts[task_id] = timeout_task
        elif strategy == CancellationStrategy.CHECKPOINT:
            try:
                checkpoint = self._checkpoint_manager.create_checkpoint(  # type: ignore[attr-defined]
                    task_id,
                    self._children_agents,
                    self._children_configs,
                    self._children_types,
                    self._parent_agent,  # type: ignore[attr-defined]
                )
                save_task = asyncio.create_task(self._checkpoint_storage.save(checkpoint))  # type: ignore[attr-defined]
                self._background_tasks.add(save_task)
                save_task.add_done_callback(self._background_tasks.discard)
                logger.info(
                    "[subagent:%s] Checkpoint scheduled (progress=%.1f%%)",
                    task_id,
                    checkpoint.progress * 100,
                )
            except Exception as e:
                logger.error("[subagent:%s] Failed to create checkpoint: %s", task_id, e)

            self._cancel_flags[task_id] = True
            logger.info("[subagent:%s] Cancel flag set (CHECKPOINT)", task_id)
            timeout_task = asyncio.create_task(
                self._graceful_cancel_timeout_handler(task_id, task, config.graceful_cancel_timeout_seconds)
            )
            self._graceful_cancel_timeouts[task_id] = timeout_task

        return True

    def cancel_all(self) -> int:
        """Cancel all running children using each child's configured strategy."""
        cancelled = 0
        for task_id, task in list(self._children.items()):
            if not task.done() and self.cancel_child(task_id):
                cancelled += 1
                logger.info("[subagent:%s] Cancel requested (parent propagation)", task_id)
        return cancelled

    def steer_child(self, task_id: str, message: str) -> bool:
        """Inject a steering message into a running child agent."""
        st = self._children_steering.get(task_id)
        if st is None:
            task = self._children.get(task_id)
            if task is None:
                logger.warning("Cannot steer task %s: not found", task_id)
                return False
            logger.warning("Cannot steer task %s: no steering token (already completed?)", task_id)
            return False
        st.steer(message)  # type: ignore[union-attr]
        logger.info("[subagent:%s] Steering message queued (%d chars)", task_id, len(message))
        return True

    async def wait_children(
        self,
        task_ids: list[str],
        min_success_rate: float = 0.5,
        timeout: float | None = None,
    ) -> dict[str, object]:
        """Wait for multiple child tasks to complete and aggregate results."""
        from .orchestrator import wait_children

        return await wait_children(self, task_ids, min_success_rate, timeout)

    async def run_chain(
        self,
        configs: list[tuple[str, SubagentConfig, str]],
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
    ) -> SubAgentResult:
        """Execute subagents in chain: A -> B -> C, each receiving previous result."""
        from .orchestrator import run_chain

        return await run_chain(self, configs, context, tool_registry_getter)

    async def run_with_verification(
        self,
        worker_type: str,
        worker_config: SubagentConfig,
        worker_task: str,
        verifier_type: str,
        verifier_config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        max_rounds: int = 2,
        verifier_task_template: str = "",
    ) -> SubAgentResult:
        """Execute a worker then verify via an adversarial verifier, retrying on failure."""
        from .orchestrator import run_with_verification

        return await run_with_verification(
            self,
            worker_type=worker_type,
            worker_config=worker_config,
            worker_task=worker_task,
            verifier_type=verifier_type,
            verifier_config=verifier_config,
            context=context,
            tool_registry_getter=tool_registry_getter,
            max_rounds=max_rounds,
            verifier_task_template=verifier_task_template,
        )

    def drain_notifications(self) -> str | None:
        """Drain all pending completion notifications."""
        return self._notification_manager.drain_notifications()  # type: ignore[attr-defined]
