"""Subagent lifecycle manager — core spawn/cancel/state-tracking.

Construction helpers live in ``builder``, composition patterns (chain, batch wait,
verified orchestration) in ``orchestrator``.

[INPUT]
- agent.types::SubagentConfig, SubAgentResult, SubAgentStatus (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)
- agent.base_agent::BaseAgent (POS: Agent base class that owns a SubagentManager instance)
- agent.security.guards.taint_tracker (POS: Taint 跨 Agent 传播追踪)
- utils.token_economics.tracker (POS: Token 用量追踪)
- .builder (POS: 子 agent 构建辅助)
- .budget::DelegationBudgetState (POS: Delegation budget guard. Tracks descendant spawn count for a root agent run without business-layer coupling.)
- .notifications::SubagentNotification, format_notification (POS: 完成通知格式化)
- .checkpoint.saver::SubagentCheckpoint, SubagentCheckpointStorage (POS: 子Agent检查点保存/恢复)
- agent.graceful_shutdown::get_shutdown_manager (POS: Graceful shutdown管理器)
- runtime.events.system_events::SubagentLifecycleData (POS: Framework-level system event DTOs. They keep lifecycle and resource payloads typed without business-layer, GUI, approval, or tenant dependencies.)

[OUTPUT]
- SubagentManager: Subagent lifecycle manager (spawn/cancel/steer/state/trace_id/push-notifications/checkpoint save/resume)
- SubagentTask: asyncio.Task[SubAgentResult] 类型别名
- CapacitySnapshot: Immutable delegation capacity snapshot for LLM decision context

[POS]
Subagent lifecycle manager. Manages spawn, cancel, steer (mid-course correction), state tracking, and trace_id propagation.

"""

from __future__ import annotations

import asyncio
import time
import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.sub_agents.types import (
    ControlScope,
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
)
from myrm_agent_harness.runtime.events.system_events import (
    SubagentLifecycleData,
    to_json_object,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.steering import SteeringToken

from .budget import DelegationBudgetExceededError, DelegationBudgetState
from .checkpoint.checkpoint_manager import SubagentCheckpointManager
from .checkpoint.saver import SubagentCheckpointStorage
from .executor import SubagentExecutor
from .notifications import NotificationManager

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)

_MAX_GLOBAL_SPAWN_DEPTH = 3
_DEFAULT_CONCURRENCY = 5
_DEFAULT_ACTIVE_CHILDREN_PER_AGENT = 5
_DEFAULT_DESCENDANTS_PER_RUN = 20

SubagentTask = asyncio.Task[SubAgentResult]


@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    """Immutable snapshot of current delegation capacity.

    Injected into delegate_task tool output so the LLM can make informed
    delegation decisions (e.g. avoid spawning when at capacity).
    """

    active_children: int
    max_children: int
    remaining_slots: int
    spawned_descendants: int
    max_descendants: int
    remaining_descendants: int


# Global registry mapping task_id to the SubagentManager that spawned it.
# ACTIVE_SUBAGENT_SESSIONS mirrors spawn session_id for REST list after parent stream ends.
# This allows Server API to find and control background subagents
# without needing complex session lifecycle binding.
ACTIVE_SUBAGENTS: weakref.WeakValueDictionary[str, SubagentManager] = weakref.WeakValueDictionary()
# Strong map task_id -> spawn session_id so REST list works after parent stream ends.
ACTIVE_SUBAGENT_SESSIONS: dict[str, str] = {}


def _emit_global_subagent_event(event_name: str, task_id: str, session_id: str, data: SubagentLifecycleData) -> None:
    try:
        from myrm_agent_harness.runtime.events import SubagentLifecycleEvent, get_event_bus

        get_event_bus().publish(
            SubagentLifecycleEvent(
                event_name=event_name,
                task_id=task_id,
                session_id=session_id,
                data=data,
            )
        )
    except Exception as e:
        logger.error("Error publishing subagent lifecycle event: %s", e)


from ._manager_control import SubagentControlMixin  # noqa: E402
from ._manager_spawn import SubagentSpawnMixin  # noqa: E402


class SubagentManager(SubagentSpawnMixin, SubagentControlMixin):
    """Subagent task lifecycle and child result tracking.

    Capabilities:
    - asyncio.Task isolation; token usage merged from child_agent.last_run_stats
    - Real-time budget check via TOKEN_USAGE streaming events
    - Parent context auto-inheritance (session_id/user_id/workspace_path)
    - Checkpointer isolation (child agents don't inherit parent's checkpointer)
    - Numeric depth control (max_spawn_depth)
    - asyncio.Semaphore concurrency enforcement
    - 4-layer tool safety (L0 type admission + L1 global blacklist + L2 config + L3 child⊆parent)
    - Cross-agent taint propagation (child taint labels → parent taint_tracker)
    - sync/async dual modes, single/parallel/chain orchestration
    - 3-level model resolution chain (config.llm → config.model → parent LLM)
    - Parent cancellation propagation
    - SubAgentStatus tracking with agent_type-aware auto-cleanup
    - Log isolation with [subagent:{task_id}] prefix
    - Result truncation (max_result_tokens)
    - Lifecycle hooks (on_spawn/on_complete/on_error)
    - Push-based completion notifications (auto-injected into parent context)
    - trace_id for parent-child call chain tracing
    - steer_child for mid-run message injection (reuses SteeringToken mechanism)
    """

    __slots__ = (
        "_background_tasks",
        "_budget_state",
        "_cancel_flags",
        "_checkpoint_manager",
        "_checkpoint_storage",
        "_children",
        "_children_agents",
        "_children_configs",
        "_children_descriptions",
        "_children_observability",
        "_children_results",
        "_children_steering",
        "_children_types",
        "_current_depth",
        "_executor",
        "_graceful_cancel_timeouts",
        "_max_children_per_agent",
        "_notification_manager",
        "_parent_agent",
        "_semaphore",
    )

    def __init__(
        self,
        parent_agent: BaseAgent,
        current_depth: int = 0,
        budget_state: DelegationBudgetState | None = None,
        max_children_per_agent: int = _DEFAULT_ACTIVE_CHILDREN_PER_AGENT,
    ) -> None:
        self._parent_agent = parent_agent
        self._children: dict[str, SubagentTask] = {}
        self._children_agents: dict[str, BaseAgent] = {}
        self._children_types: dict[str, str] = {}
        self._children_descriptions: dict[str, str] = {}
        self._children_results: dict[str, SubAgentResult] = {}
        self._children_steering: dict[str, SteeringToken] = {}
        self._children_configs: dict[str, SubagentConfig] = {}
        self._children_observability: dict[str, dict[str, object]] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._graceful_cancel_timeouts: dict[str, asyncio.Task[None]] = {}
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._semaphore = asyncio.Semaphore(_DEFAULT_CONCURRENCY)
        self._current_depth = current_depth
        self._budget_state = budget_state or DelegationBudgetState(max_descendants=_DEFAULT_DESCENDANTS_PER_RUN)
        self._max_children_per_agent = max_children_per_agent
        self._notification_manager = NotificationManager()
        self._checkpoint_storage = SubagentCheckpointStorage()
        self._checkpoint_manager = SubagentCheckpointManager()
        self._executor = SubagentExecutor()

        # Register graceful shutdown callback for checkpoint save
        from myrm_agent_harness.agent.hooks.graceful_shutdown import (
            get_shutdown_manager,
        )

        shutdown_manager = get_shutdown_manager()
        shutdown_manager.register_checkpoint_callback(self._save_all_checkpoints)
        shutdown_manager.register_signals()  # Auto-register signals (idempotent)

    @property
    def children(self) -> Mapping[str, SubagentTask]:
        return MappingProxyType(self._children)

    @property
    def child_results(self) -> Mapping[str, SubAgentResult]:
        return MappingProxyType(self._children_results)

    @property
    def current_depth(self) -> int:
        return self._current_depth

    @property
    def budget_state(self) -> DelegationBudgetState:
        return self._budget_state

    def get_capacity_snapshot(self) -> CapacitySnapshot:
        """Return current delegation capacity for LLM decision context."""
        active = sum(1 for t in self._children.values() if not t.done())
        max_ch = self._max_children_per_agent
        return CapacitySnapshot(
            active_children=active,
            max_children=max_ch,
            remaining_slots=max(0, max_ch - active),
            spawned_descendants=self._budget_state.spawned_descendants,
            max_descendants=self._budget_state.max_descendants,
            remaining_descendants=max(
                0,
                self._budget_state.max_descendants - self._budget_state.spawned_descendants,
            ),
        )

    def inherit_runtime_limits(
        self,
        *,
        current_depth: int,
        budget_state: DelegationBudgetState,
        max_children_per_agent: int,
    ) -> None:
        """Inherit scoped delegation runtime limits from the parent manager."""
        self._current_depth = current_depth
        self._budget_state = budget_state
        self._max_children_per_agent = max_children_per_agent

    # =========================================================================
    # Checkpoint Management (delegated to SubagentCheckpointManager)
    # =========================================================================

    def _save_all_checkpoints(self) -> None:
        """Save checkpoints for all running children (delegated to checkpoint manager)."""
        self._checkpoint_manager.save_all_checkpoints(
            self._children,
            self._children_agents,
            self._children_configs,
            children_types=self._children_types,
            children_descriptions=self._children_descriptions,
        )

    async def resume_from_checkpoint(self, task_id: str) -> SubAgentResult:
        """Resume subagent from saved checkpoint (delegated to checkpoint manager)."""
        return await self._checkpoint_manager.resume_from_checkpoint(task_id)

    # =========================================================================
    # Validation
    # =========================================================================

    def _task_id_exists(self, task_id: str) -> bool:
        return task_id in self._children or task_id in self._children_results

    def _validate_depth(self, task_id: str, config: SubagentConfig) -> SubAgentResult | None:
        if self._current_depth >= _MAX_GLOBAL_SPAWN_DEPTH:
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type="",
                error=f"Max spawn depth ({_MAX_GLOBAL_SPAWN_DEPTH}) reached at depth {self._current_depth}",
                completed_at=time.time(),
                status=SubAgentStatus.FAILED,
            )
        if config.control_scope == ControlScope.ORCHESTRATOR and self._current_depth >= config.max_spawn_depth:
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type="",
                error=f"Config max_spawn_depth={config.max_spawn_depth} exceeded at depth {self._current_depth}",
                completed_at=time.time(),
                status=SubAgentStatus.FAILED,
            )
        return None

    def _validate_capacity(self, task_id: str, agent_type: str, config: SubagentConfig) -> SubAgentResult | None:
        active_children = sum(1 for task in self._children.values() if not task.done())
        max_active_children = min(
            self._max_children_per_agent,
            max(1, config.max_children_per_agent),
        )
        if active_children >= max_active_children:
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error=(
                    f"Active child limit exceeded: {active_children}/{max_active_children} children already running"
                ),
                completed_at=time.time(),
                status=SubAgentStatus.FAILED,
                payload={
                    "reason": "budget_exceeded",
                    "limit_type": "max_children_per_agent",
                    "active_children": active_children,
                    "max_children_per_agent": max_active_children,
                },
            )
        try:
            self._budget_state.reserve()
        except DelegationBudgetExceededError as error:
            return SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error=str(error),
                completed_at=time.time(),
                status=SubAgentStatus.FAILED,
                payload={
                    "reason": "budget_exceeded",
                    "limit_type": "max_descendants_per_run",
                    **self._budget_state.snapshot(),
                },
            )
        return None

    # =========================================================================
    # Core Execution
    # =========================================================================

    def _cleanup_child(self, task_id: str, task: SubagentTask) -> None:
        timeout_task = self._graceful_cancel_timeouts.pop(task_id, None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()

        agent_type = self._children_types.pop(task_id, "unknown")
        self._children_configs.pop(task_id, None)
        self._children_descriptions.pop(task_id, None)
        now = time.time()

        if task.cancelled():
            result = SubAgentResult(
                success=False,
                task_id=task_id,
                agent_type=agent_type,
                error="Cancelled",
                completed_at=now,
                status=SubAgentStatus.CANCELLED,
            )
        else:
            try:
                result = task.result()
                if not result.completed_at:
                    result.completed_at = now
            except Exception as error:
                result = SubAgentResult(
                    success=False,
                    task_id=task_id,
                    agent_type=agent_type,
                    error=f"{type(error).__name__}: {error}",
                    completed_at=now,
                    status=SubAgentStatus.FAILED,
                )

        self._children_results[task_id] = result
        self._children.pop(task_id, None)
        self._children_steering.pop(task_id, None)
        ACTIVE_SUBAGENTS.pop(task_id, None)  # Remove from global registry
        ACTIVE_SUBAGENT_SESSIONS.pop(task_id, None)
        self._purge_expired_results()

        # Cleanup file conflict tracking data for completed subagent
        try:
            from myrm_agent_harness.agent.meta_tools.file_ops.core.file_activity_tracker import (
                get_file_activity_tracker,
            )
            from myrm_agent_harness.agent.meta_tools.file_ops.core.file_integrity_guard import (
                _integrity_guards,
            )

            get_file_activity_tracker().clear_agent(task_id)
            for guard in _integrity_guards.values():
                guard.clear_agent(task_id)
        except Exception:
            pass

        self._notification_manager.add_notification(result, now)
        session_id = ""
        if hasattr(self._parent_agent, "session_id"):
            session_id = str(getattr(self._parent_agent, "session_id", ""))
        if session_id:
            from myrm_agent_harness.agent.coordination.mailbox import (
                unregister_active_teammate,
            )

            unregister_active_teammate(session_id, task_id)
        metadata = self._child_observability_metadata(task_id)
        budget = metadata.get("budget")

        _emit_global_subagent_event(
            "complete",
            task_id,
            session_id,
            SubagentLifecycleData(
                agent_type=result.agent_type,
                description=self._children_descriptions.get(task_id, ""),
                role=str(metadata.get("role", "")),
                control_scope=str(metadata.get("control_scope", "")),
                budget=to_json_object(budget if isinstance(budget, dict) else None),
                status=result.status.value,
                result=to_json_object(result.to_dict()),
            ),
        )

        # Idle Wakeup & Event-Driven Continuation (Trigger Parent Agent if supported)
        if hasattr(self._parent_agent, "trigger_async_wakeup"):
            # Trigger the parent agent with the background task result
            try:
                # We do this asynchronously to avoid blocking cleanup
                wakeup_task = asyncio.create_task(self._parent_agent.trigger_async_wakeup(result))
                self._background_tasks.add(wakeup_task)
                wakeup_task.add_done_callback(self._background_tasks.discard)
            except Exception as e:
                logger.error("Failed to trigger async wakeup for parent agent: %s", e)

    def _purge_expired_results(self) -> None:
        """Evict oldest completed results (FIFO by completed_at) when cache exceeds 50 entries."""
        if len(self._children_results) <= 50:
            return
        completed = [(tid, r) for tid, r in self._children_results.items() if r.status != SubAgentStatus.RUNNING]
        completed.sort(key=lambda x: x[1].completed_at)
        evict_count = len(self._children_results) - 50
        for tid, _ in completed[:evict_count]:
            del self._children_results[tid]
            self._children_observability.pop(tid, None)

    def _build_observability_metadata(self, config: SubagentConfig) -> dict[str, object]:
        budget: dict[str, object] = {
            "timeout_seconds": config.timeout_seconds,
        }
        if config.max_cost_usd is not None:
            budget["max_cost_usd"] = config.max_cost_usd
        if config.budget_tokens is not None:
            budget["budget_tokens"] = config.budget_tokens
        metadata: dict[str, object] = {
            "role": config.delegation_role.value,
            "control_scope": config.control_scope.value,
            "budget": budget,
        }
        if config.model:
            metadata["effective_model"] = config.model
        return metadata

    def _child_observability_metadata(self, task_id: str) -> dict[str, object]:
        snapshot = self._children_observability.get(task_id)
        if snapshot is not None:
            return dict(snapshot)
        config = self._children_configs.get(task_id)
        if config is None:
            return {}
        return self._build_observability_metadata(config)
