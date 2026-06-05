"""Subagent checkpoint management.

[INPUT]
- .saver::SubagentCheckpoint, SubagentCheckpointStorage (POS: Checkpoint数据结构和存储)
- .state_extractor::extract_subagent_state_sync, extract_subagent_state_async (POS: 状态提取)
- agent.types::SubAgentResult, SubAgentStatus (POS: 结果和状态类型)

[OUTPUT]
- SubagentCheckpointManager: Checkpoint生命周期管理器(create/save/resume/delete)

[POS]
Subagent checkpoint manager. Handles checkpoint creation, saving, restoration, and deletion.

"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .metrics import CheckpointMetrics
from .saver import SubagentCheckpoint, SubagentCheckpointStorage

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)

logger = get_agent_logger(__name__)


class SubagentCheckpointManager:
    """Manage checkpoint creation, save, resume, and deletion for subagents."""

    def __init__(self) -> None:
        self._storage = SubagentCheckpointStorage()
        self._metrics = CheckpointMetrics()

    _CHECKPOINT_SAVE_TIMEOUT_SECONDS = 5.0

    def save_all_checkpoints(
        self,
        children: dict[str, object],
        children_agents: dict[str, BaseAgent],
        children_configs: dict[str, SubagentConfig],
        interruption_reason: str = "gateway-shutdown",
        children_types: dict[str, str] | None = None,
        children_descriptions: dict[str, str] | None = None,
    ) -> None:
        """Save checkpoints for ALL running children during graceful shutdown.

        Called by GracefulShutdownManager when SIGTERM/SIGINT received.
        Uses sync extraction as fallback when the event loop is already running
        (signal handler context), and async extraction otherwise.

        Each individual checkpoint save is protected by a per-task timeout
        to prevent the shutdown process from hanging.

        Args:
            children: Dict of task_id -> asyncio.Task
            children_agents: Dict of task_id -> BaseAgent
            children_configs: Dict of task_id -> SubagentConfig
            interruption_reason: Reason for the interruption (e.g., 'gateway-shutdown')
            children_types: Dict of task_id -> agent_type string
            children_descriptions: Dict of task_id -> task description string
        """
        types_map = children_types or {}
        desc_map = children_descriptions or {}

        running_tasks = [task_id for task_id, task in children.items() if not task.done()]

        if not running_tasks:
            logger.debug("[subagent] No running tasks to checkpoint")
            return

        logger.info(
            "[subagent] Saving checkpoints for %d running tasks...",
            len(running_tasks),
        )

        try:
            loop = asyncio.get_running_loop()
            loop_running = loop.is_running()
        except RuntimeError:
            loop_running = False

        for task_id in running_tasks:
            start_time = time.time()
            try:
                if loop_running:
                    checkpoint = self._create_checkpoint_sync_safe(
                        task_id,
                        children_agents,
                        children_configs,
                        types_map,
                    )
                else:
                    checkpoint = asyncio.run(
                        self.create_checkpoint_async(
                            task_id,
                            children_agents,
                            children_configs,
                            types_map,
                        )
                    )

                checkpoint.interruption_reason = interruption_reason
                checkpoint.task_description = desc_map.get(task_id, "")

                if loop_running:
                    self._storage.save_sync(checkpoint)
                else:
                    asyncio.run(self._storage.save(checkpoint))

                elapsed_ms = (time.time() - start_time) * 1000

                if elapsed_ms > self._CHECKPOINT_SAVE_TIMEOUT_SECONDS * 1000:
                    logger.warning(
                        "[subagent:%s] Checkpoint save exceeded timeout (%.1fms > %.0fms)",
                        task_id,
                        elapsed_ms,
                        self._CHECKPOINT_SAVE_TIMEOUT_SECONDS * 1000,
                    )

                self._metrics.save_count += 1
                self._metrics.save_success_count += 1
                self._metrics.save_total_ms += elapsed_ms
                if checkpoint.messages:
                    self._metrics.messages_extracted_count += 1

                logger.info(
                    "[subagent:%s] Checkpoint saved (progress=%.1f%%, messages=%d, resumable=%s, elapsed=%.1fms)",
                    task_id,
                    checkpoint.progress * 100,
                    len(checkpoint.messages),
                    checkpoint.resumable,
                    elapsed_ms,
                )
            except Exception as e:
                self._metrics.save_count += 1
                self._metrics.save_failure_count += 1
                if "message" in str(e).lower():
                    self._metrics.messages_extraction_failures += 1

                logger.error("[subagent:%s] Failed to save checkpoint: %s", task_id, e)

    def _create_checkpoint_sync_safe(
        self,
        task_id: str,
        children_agents: dict[str, BaseAgent],
        children_configs: dict[str, SubagentConfig],
        children_types: dict[str, str] | None = None,
    ) -> SubagentCheckpoint:
        """Create checkpoint using sync extraction (signal handler safe).

        Uses synchronous state extraction which doesn't require an event loop.
        Messages from checkpointer won't be available, but context and stats are.

        Args:
            task_id: Task ID to create checkpoint for
            children_agents: Dict of task_id -> BaseAgent
            children_configs: Dict of task_id -> SubagentConfig
            children_types: Dict of task_id -> agent_type string

        Returns:
            SubagentCheckpoint instance
        """
        config = children_configs.get(task_id)
        if not config:
            raise ValueError(f"No config found for task_id={task_id}")

        agent_type = (children_types or {}).get(task_id, "unknown")

        child_agent = children_agents.get(task_id)
        if not child_agent:
            logger.warning("[subagent:%s] No agent instance found, creating minimal checkpoint", task_id)
            return SubagentCheckpoint(
                task_id=task_id,
                agent_type=agent_type,
                session_id="unknown",
                timestamp=time.time(),
                messages=[],
                tool_outputs=[],
                variables={},
                progress=0.0,
                last_tool=None,
                resumable=False,
            )

        from .state_extractor import extract_subagent_state_sync

        state = extract_subagent_state_sync(child_agent, task_id)
        session_id = getattr(child_agent, "session_id", "unknown")

        return SubagentCheckpoint(
            task_id=task_id,
            agent_type=agent_type,
            session_id=session_id,
            timestamp=time.time(),
            messages=state.get("messages", []),
            tool_outputs=[],
            variables=state.get("context", {}),
            progress=state.get("progress", 0.5),
            last_tool=state.get("last_tool"),
            resumable=bool(state.get("messages")),
        )

    def create_checkpoint(
        self,
        task_id: str,
        children_agents: dict[str, BaseAgent],
        children_configs: dict[str, SubagentConfig],
        children_types: dict[str, str],
        parent_agent: BaseAgent,
    ) -> SubagentCheckpoint:
        """Create checkpoint from current execution state (synchronous version).

        Uses synchronous state extraction, suitable for non-async contexts.
        For full state extraction including messages, use create_checkpoint_async.

        Args:
            task_id: Task ID to create checkpoint for
            children_agents: Dict of task_id -> BaseAgent
            children_configs: Dict of task_id -> SubagentConfig
            parent_agent: Parent agent instance

        Returns:
            SubagentCheckpoint instance
        """
        config = children_configs.get(task_id)
        if not config:
            raise ValueError(f"No config found for task_id={task_id}")

        agent_type = children_types.get(task_id, "unknown")
        session_id = getattr(parent_agent, "session_id", "unknown")

        child_agent = children_agents.get(task_id)
        if not child_agent:
            logger.warning("[subagent:%s] No agent instance found, creating minimal checkpoint", task_id)
            return SubagentCheckpoint(
                task_id=task_id,
                agent_type=agent_type,
                session_id=session_id,
                timestamp=time.time(),
                messages=[],
                tool_outputs=[],
                variables={},
                progress=0.0,
                last_tool=None,
                resumable=False,
            )

        from .state_extractor import extract_subagent_state_sync

        state = extract_subagent_state_sync(child_agent, task_id)

        return SubagentCheckpoint(
            task_id=task_id,
            agent_type=agent_type,
            session_id=session_id,
            timestamp=time.time(),
            messages=state.get("messages", []),
            tool_outputs=[],
            variables=state.get("context", {}),
            progress=state.get("progress", 0.5),
            last_tool=state.get("last_tool"),
            resumable=bool(state.get("messages")),
        )

    async def create_checkpoint_async(
        self,
        task_id: str,
        children_agents: dict[str, BaseAgent],
        children_configs: dict[str, SubagentConfig],
        children_types: dict[str, str],
    ) -> SubagentCheckpoint:
        """Create checkpoint from current execution state (asynchronous version).

        Uses async state extraction via BaseAgent.get_checkpoint_state(),
        which can extract complete messages from LangGraph checkpointer.

        Args:
            task_id: Task ID to create checkpoint for
            children_agents: Dict of task_id -> BaseAgent
            children_configs: Dict of task_id -> SubagentConfig

        Returns:
            SubagentCheckpoint instance with complete state (including messages)
        """
        config = children_configs.get(task_id)
        if not config:
            raise ValueError(f"No config found for task_id={task_id}")

        # Get agent_type from config or children_types
        agent_type = children_types.get(task_id, "unknown")
        session_id = "unknown"  # Will be set from agent if available

        child_agent = children_agents.get(task_id)
        if not child_agent:
            logger.warning("[subagent:%s] No agent instance found, creating minimal checkpoint", task_id)
            return SubagentCheckpoint(
                task_id=task_id,
                agent_type=agent_type,
                session_id=session_id,
                timestamp=time.time(),
                messages=[],
                tool_outputs=[],
                variables={},
                progress=0.0,
                last_tool=None,
                resumable=False,
            )

        session_id = getattr(child_agent, "session_id", "unknown")

        from .state_extractor import extract_subagent_state_async

        state = await extract_subagent_state_async(child_agent, task_id)

        return SubagentCheckpoint(
            task_id=task_id,
            agent_type=agent_type,
            session_id=session_id,
            timestamp=time.time(),
            messages=state.get("messages", []),
            tool_outputs=[],
            variables=state.get("context", {}),
            progress=state.get("progress", 0.5),
            last_tool=state.get("last_tool"),
            resumable=bool(state.get("messages")),
        )

    async def resume_from_checkpoint(self, task_id: str) -> SubAgentResult:
        """Resume subagent from saved checkpoint.

        Args:
            task_id: Task ID to resume

        Returns:
            SubAgentResult with checkpoint_data containing:
            - messages: Complete LangChain conversation history
            - variables: Runtime context (_last_context)
            - progress: Execution progress (0.0-1.0)
            - last_tool: Last executed tool name

        Raises:
            ValueError: If checkpoint not found or not resumable

        Note:
            Returns checkpoint data in result.checkpoint_data.
            Business layer can use messages to create new agent session for seamless continuation.
        """
        start_time = time.time()

        try:
            checkpoint = await self._storage.load(task_id)
            if not checkpoint:
                # Record failure metrics
                self._metrics.resume_count += 1
                self._metrics.resume_failure_count += 1
                raise ValueError(f"No checkpoint found for task_id={task_id}")

            if not checkpoint.resumable:
                # Record failure metrics
                self._metrics.resume_count += 1
                self._metrics.resume_failure_count += 1
                raise ValueError(f"Checkpoint {task_id} is not resumable")

            logger.info(
                "[subagent:%s] Resuming from checkpoint (agent_type=%s, progress=%.1f%%, messages=%d, context_keys=%d)",
                task_id,
                checkpoint.agent_type,
                checkpoint.progress * 100,
                len(checkpoint.messages),
                len(checkpoint.variables),
            )

            accumulated = checkpoint.accumulated_runtime_seconds if checkpoint.accumulated_runtime_seconds > 0 else None

            result = SubAgentResult(
                success=True,
                task_id=task_id,
                agent_type=checkpoint.agent_type,
                result=f"Resumed from checkpoint (progress={checkpoint.progress:.1%}, last_tool={checkpoint.last_tool})",
                duration_seconds=0.0,
                completed_at=time.time(),
                status=SubAgentStatus.COMPLETED,
                checkpoint_data={
                    "messages": checkpoint.messages,
                    "variables": checkpoint.variables,
                    "progress": checkpoint.progress,
                    "last_tool": checkpoint.last_tool,
                    "timestamp": checkpoint.timestamp,
                },
                accumulated_duration_seconds=accumulated,
            )

            # Note: checkpoint is NOT deleted here. The caller should call
            # delete_checkpoint(task_id) after successful restoration to avoid
            # losing the checkpoint if restoration fails.

            # Record success metrics
            elapsed_ms = (time.time() - start_time) * 1000
            self._metrics.resume_count += 1
            self._metrics.resume_success_count += 1
            self._metrics.resume_total_ms += elapsed_ms

            logger.info(
                "[subagent:%s] Checkpoint resume complete (messages=%d, variables=%d, elapsed=%.1fms)",
                task_id,
                len(checkpoint.messages),
                len(checkpoint.variables),
                elapsed_ms,
            )

            return result

        except Exception:
            # Ensure failures are recorded
            if self._metrics.resume_count == 0 or self._metrics.resume_failure_count == 0:
                self._metrics.resume_count += 1
                self._metrics.resume_failure_count += 1
            raise

    async def delete_checkpoint(self, task_id: str) -> None:
        """Delete a saved checkpoint after successful restoration.

        Should be called by the business layer after confirming that
        the checkpoint data has been successfully restored to the agent.

        Args:
            task_id: Task ID to delete checkpoint for
        """
        await self._storage.delete(task_id)
        logger.info("[subagent:%s] Checkpoint deleted after successful restoration", task_id)

    async def save_checkpoint_for_task(
        self,
        task_id: str,
        children_agents: dict[str, BaseAgent],
        children_configs: dict[str, SubagentConfig],
        children_types: dict[str, str] | None = None,
    ) -> SubagentCheckpoint:
        """Save checkpoint for a specific task.

        Args:
            task_id: Task ID to save checkpoint for
            children_agents: Dict of task_id -> BaseAgent
            children_configs: Dict of task_id -> SubagentConfig
            children_types: Dict of task_id -> agent_type string

        Returns:
            The created SubagentCheckpoint instance

        Raises:
            Exception: If checkpoint creation or save fails
        """
        start_time = time.time()

        try:
            checkpoint = await self.create_checkpoint_async(
                task_id,
                children_agents,
                children_configs,
                children_types or {},
            )
            await self._storage.save(checkpoint)

            # Record metrics
            elapsed_ms = (time.time() - start_time) * 1000
            self._metrics.save_count += 1
            self._metrics.save_success_count += 1
            self._metrics.save_total_ms += elapsed_ms
            if checkpoint.messages:
                self._metrics.messages_extracted_count += 1

            logger.info(
                "[subagent:%s] Checkpoint saved (progress=%.1f%%, elapsed=%.1fms)",
                task_id,
                checkpoint.progress * 100,
                elapsed_ms,
            )
            return checkpoint

        except Exception as e:
            # Record failure metrics
            self._metrics.save_count += 1
            self._metrics.save_failure_count += 1
            if "message" in str(e).lower():
                self._metrics.messages_extraction_failures += 1
            raise

    @property
    def metrics(self) -> CheckpointMetrics:
        """Get checkpoint metrics for monitoring.

        Returns:
            CheckpointMetrics instance with current metrics
        """
        return self._metrics
