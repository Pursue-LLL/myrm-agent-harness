"""Integration helpers for skill evolution system.

Makes it easy for business layer to enable evolution capabilities.
Framework provides the hooks, business layer decides when to use them.

[INPUT]
- agent.skills.evolution.core.types::EvolutionProposal, (POS: Data types for skill evolution system.)
- agent.skills.evolution.core.engine::SkillEvolutionEngine (POS: Skill evolution engine - Core of self-evolution system.)
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)
- toolkits.code_execution.executors.test_executor::SubprocessCodeExecutor (POS: Subprocess-based test execution for skill evolution TDE.)
- agent.skills.evolution.execution.tool_selector::EvolutionToolConfig (POS: Tool Selector for Evolution System)
- agent.skills.evolution.pipeline.screener::EvolutionScreener (POS: myrm_agent_harness/agent/skills/evolution/screener.py ## Architecture Two-phase screening to block "snowball effect" of blind fixes: **Phase 1: Rule-based (Cooldown)** Rejects repeated evolution attempts within cooldown period Checks both skill.updated_at and rejection history Zero LLM cost, instant response **Phase 2: LLM Confirmation (Cheap Model)** Only for FIX evolution type Analyzes real error logs (HTTP status, exception stack) Asks cheap LLM: "Is this really a skill code defect?" Returns YES (proceed) or NO + reason (block) **Prometheus Metrics (Observability)** evolution_screening_total: Counter by phase + result evolution_screening_confidence: Histogram of LLM confidence evolution_screening_duration_seconds: Histogram of screening duration by phase ## Design Principles 1. **Cost Optimization**: Use gpt-4o-mini/claude-haiku for Phase 2 2. **Fail-Safe**: LLM errors → Allow (don't block valid fixes) 3. **Transparency**: Record all rejections for audit 4. **Signal Extraction**: Focus on HTTP status + exception type vs full stack 5. **Observability**: Expose Prometheus metrics for monitoring and tuning)
- agent.context_management.pipeline::ContextPipeline (POS: Message filter pipeline for composing multiple filters.)
- toolkits.code_execution::CodeExecutor (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)
- toolkits.web_search::SearchServiceConfig (POS: Web search toolkit entry point. Aggregates and re-exports search tools, result types, metrics, and error hierarchy for unified import.)
- agent.middlewares._session_context::get_approval_session (POS: Middleware session context — shared ContextVars for the middleware chain.)
- agent.hooks.executor::fire_hook (POS: Hook execution layer. Manages hook registration and execution with ContextVar-based session isolation.)

[OUTPUT]
- EvolutionIntegration: All-in-one integration helper for skill evolution.
- get_global_evolution_integration: Get the global EvolutionIntegration instance if configured.
- set_global_evolution_integration: Set the global EvolutionIntegration instance.
- enable_skill_evolution: Enable skill evolution with one function call.

[POS]
Integration helpers for skill evolution system. Provides EvolutionIntegration singleton with
15-Call Sliding Window trigger, execution ledger recording, and background queue orchestration.
"""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.agent.skills.evolution.core.engine import SkillEvolutionEngine
from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionProposal,
    EvolutionRequest,
    EvolutionType,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.execution.dependency import (
    get_dependency_tracker,
)
from myrm_agent_harness.agent.skills.evolution.execution.tool_selector import (
    EvolutionToolConfig,
)
from myrm_agent_harness.agent.skills.evolution.infra.metrics import get_metrics_tracker
from myrm_agent_harness.agent.skills.evolution.infra.queue import (
    EvolutionQueue,
    QueuePriority,
    get_evolution_queue,
)
from myrm_agent_harness.agent.skills.evolution.infra.tracker import (
    SkillExecutionResult,
    SkillQualityTracker,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.screener import (
    EvolutionScreener,
)
from myrm_agent_harness.toolkits.code_execution.executors.test_executor import (
    SubprocessCodeExecutor,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.context_management.pipeline import ContextPipeline
    from myrm_agent_harness.agent.skills.evolution.safety.anti_loop_state import AntiLoopState
    from myrm_agent_harness.toolkits.code_execution import CodeExecutor
    from myrm_agent_harness.toolkits.web_search import SearchServiceConfig

logger = logging.getLogger(__name__)


_global_evolution_integration: "EvolutionIntegration | None" = None


def get_global_evolution_integration() -> "EvolutionIntegration | None":
    """Get the global EvolutionIntegration instance if configured."""
    return _global_evolution_integration


def set_global_evolution_integration(
    integration: "EvolutionIntegration | None",
) -> None:
    """Set the global EvolutionIntegration instance."""
    global _global_evolution_integration
    _global_evolution_integration = integration


class EvolutionIntegration:
    """All-in-one integration helper for skill evolution.

    Framework-layer helper that provides out-of-the-box evolution capabilities.
    Business layer can enable evolution by instantiating this class.

    Example (business layer):
        ```python
        from myrm_agent_harness.agent.skills.evolution import EvolutionIntegration

        # Enable evolution with one line
        evolution = EvolutionIntegration(
            db_path=".myrm/skills_evolution.db",
            llm=your_chat_model)

        # Record skill execution result
        await evolution.record_execution(skill_id="test", success=False, error_message="...")

        # Auto-evolve in background
        await evolution.start_background_queue()
        ```
    """

    def __init__(
        self,
        db_path: Path | str = ".myrm/skills_evolution.db",
        *,
        llm: BaseChatModel | None = None,
        context_pipeline: "ContextPipeline | None" = None,
        enable_background_queue: bool = False,
        queue_workers: int = 2,
        max_concurrent_evolutions: int = 5,
        anti_loop_state: "AntiLoopState | None" = None,
        screener: "EvolutionScreener | None" = None,
        enable_background_tasks: bool = False,
        background_shutdown_timeout: float = 30.0,
        max_concurrent_background: int = 5,
        enable_tde: bool = False,
        test_executor: "SubprocessCodeExecutor | None" = None,
        enable_tool_calling: bool = False,
        evolution_tools: "list[BaseTool] | None" = None,
        tool_config: "EvolutionToolConfig | None" = None,
        executor: "CodeExecutor | None" = None,
        workspace_path: Path | str | None = None,
        search_service_cfg: "SearchServiceConfig | None" = None,
        auto_apply_fs: bool = False,
        event_log_backend: Any | None = None,
        evolution_strategy: str = "balanced",
    ):
        """Initialize evolution integration.

        Args:
            db_path: Path to SQLite database for skill storage
            llm: LLM client for evolution (BaseChatModel, business layer provides)
            context_pipeline: Optional context management pipeline (auto-created if None)
            enable_background_queue: Enable background evolution queue
            queue_workers: Number of queue workers (if enabled)
            max_concurrent_evolutions: Max concurrent evolution tasks (default 5, for all deployment modes)
            anti_loop_state: Anti-loop state backend (auto-creates InMemoryAntiLoopState if None)
            screener: Optional EvolutionScreener instance for two-phase filtering (injected by business layer)
            enable_background_tasks: Enable background task management (default False)
            background_shutdown_timeout: Background task shutdown timeout in seconds (default 30.0)
            max_concurrent_background: Max concurrent background tasks (default 5)
            enable_tde: Enable test-driven evolution with generated pytest validation (default False)
            test_executor: Optional subprocess test executor (auto-created if enable_tde=True and None)
            enable_tool_calling: Enable Evolution Agent tool calling (default False, +8-12% success rate)
            evolution_tools: Pre-configured tools (auto-created if None and enable_tool_calling=True)
            tool_config: Tool configuration (limits, smart error handling, etc.)
            executor: Executor for file operations (auto-created if None)
            workspace_path: Workspace path for executor (defaults to db_path.parent)
            search_service_cfg: Web search config injected by business layer (required when auto-creating evolution tools)
            auto_apply_fs: Auto-apply evolved content to file system with .bak backup (default False)
            evolution_strategy: Controls screener behavior: balanced (all types),
                innovate (all + lower rejection threshold), harden (FIX + optimize only),
                repair-only (FIX only). Business layer injects user preference.
        """
        self.db_path = Path(db_path)

        # Core components
        self.store = SkillStore(self.db_path)
        self.tracker = SkillQualityTracker(self.store)
        self.test_executor: SubprocessCodeExecutor | None = test_executor
        self.screener: EvolutionScreener | None = screener
        self._evolution_strategy = evolution_strategy

        # Propagate strategy to screener if injected
        if self.screener is not None:
            self.screener.evolution_strategy = evolution_strategy

        # Evolution engine (requires LLM client from business layer)
        self.engine: SkillEvolutionEngine | None = None
        self.executor: CodeExecutor | None = executor

        if llm:
            # Auto-create executor if needed
            if enable_tool_calling and self.executor is None:
                from myrm_agent_harness.toolkits.code_execution import create_executor

                # Note: workspace_path param is for documentation only;
                # executor uses current working directory by default
                self.executor = create_executor()
                logger.debug("EvolutionIntegration: auto-created executor")

            # Auto-create evolution tools if needed
            if enable_tool_calling and evolution_tools is None and self.executor:
                from ..execution.tool_selector import (
                    EvolutionToolConfig,
                    create_evolution_tools,
                )

                if search_service_cfg is None:
                    logger.warning(
                        "EvolutionIntegration: enable_tool_calling=True but no "
                        "search_service_cfg injected — web_search tool omitted"
                    )
                tool_config = tool_config or EvolutionToolConfig()
                evolution_tools = create_evolution_tools(
                    executor=self.executor,
                    search_service_cfg=search_service_cfg,
                    config=tool_config,
                )
                logger.debug(
                    "EvolutionIntegration: auto-created evolution tools (%d tools)",
                    len(evolution_tools),
                )

            if enable_tde and self.test_executor is None:
                self.test_executor = SubprocessCodeExecutor()
                logger.debug("EvolutionIntegration: auto-created subprocess test executor")

            self.engine = SkillEvolutionEngine(
                store=self.store,
                llm=llm,
                event_log_backend=event_log_backend,
                max_concurrent_evolutions=max_concurrent_evolutions,
            )

        # Optional components
        self.dependency_tracker = get_dependency_tracker()
        self.metrics_tracker = get_metrics_tracker()

        self.queue: EvolutionQueue | None = None
        if enable_background_queue:
            self.queue = get_evolution_queue(worker_count=queue_workers)

        logger.info(
            "Evolution integration initialized: db=%s, llm=%s, queue=%s",
            self.db_path,
            llm is not None,
            enable_background_queue,
        )

        # Per-session sliding window state for trace slice trigger
        # Key: session_id, Value: (call_count_since_last_slice, collected_tool_call_ids)
        self._slice_cursors: dict[str, tuple[int, list[str]]] = {}

        # Register as global instance so middlewares can access it
        set_global_evolution_integration(self)

    @property
    def evolution_strategy(self) -> str:
        """Current evolution strategy."""
        return self._evolution_strategy

    @evolution_strategy.setter
    def evolution_strategy(self, value: str) -> None:
        """Hot-update evolution strategy (propagates to screener)."""
        self._evolution_strategy = value
        if self.screener is not None:
            self.screener.evolution_strategy = value
        logger.info("Evolution strategy updated to '%s'", value)

    SLICE_WINDOW_THRESHOLD: int = 15

    def register_hooks(self, registry: Any) -> None:
        """Register framework hooks for evolution (TRACE_SLICE_READY + window trigger).

        Safe to call multiple times — skips if already registered.
        """
        from myrm_agent_harness.agent.hooks.types import (
            CallableHookDefinition,
            HookEvent,
        )

        existing = registry._hooks.get(HookEvent.POST_TOOL_USE, [])
        if any(getattr(h, "fn", None) and getattr(h.fn, "__name__", "") == "_window_counter" for h in existing):
            return

        async def _handle_trace_slice(event: str, payload: dict[str, object]) -> Any:
            from myrm_agent_harness.agent.hooks.types import HookResult

            session_id = str(payload.get("session_id", ""))

            tool_call_ids = payload.get("tool_call_ids", [])
            if not isinstance(tool_call_ids, list):
                tool_call_ids = []

            agent_id = payload.get("agent_id")
            agent_id = str(agent_id) if agent_id else None

            if self.queue and session_id and tool_call_ids:
                try:
                    await self.queue.enqueue(
                        EvolutionRequest(
                            evolution_type=EvolutionType.SLICE_EXTRACTION,
                            skill_id=f"slice_{session_id}_{len(tool_call_ids)}_calls",
                            reason="Background trace slice extraction",
                            session_id=session_id,
                            tool_call_ids=cast("list[str]", tool_call_ids),
                            agent_id=agent_id,
                        ),
                        priority=QueuePriority.LOW,
                    )
                except Exception as e:
                    logger.warning("Failed to enqueue trace slice: %s", e)
            return HookResult(hook_type="callable", success=True)

        async def _window_counter(event: str, payload: dict[str, object]) -> Any:
            """Count tool calls per session; emit TRACE_SLICE_READY at threshold."""
            from myrm_agent_harness.agent.hooks.executor import fire_hook
            from myrm_agent_harness.agent.hooks.types import HookResult
            from myrm_agent_harness.agent.middlewares._session_context import (
                get_agent_id,
                get_approval_session,
            )

            tool_call_id = payload.get("tool_call_id")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                return HookResult(hook_type="callable", success=True)

            session_id = get_approval_session()
            if not session_id:
                return HookResult(hook_type="callable", success=True)

            count, ids = self._slice_cursors.get(session_id, (0, []))
            ids.append(tool_call_id)
            count += 1

            if count >= self.SLICE_WINDOW_THRESHOLD:
                agent_id = get_agent_id() or None
                await fire_hook(
                    HookEvent.TRACE_SLICE_READY,
                    {
                        "session_id": session_id,
                        "tool_call_ids": ids,
                        "agent_id": agent_id,
                    },
                )
                self._slice_cursors[session_id] = (0, [])
            else:
                self._slice_cursors[session_id] = (count, ids)

            if len(self._slice_cursors) > 1000:
                oldest_key = next(iter(self._slice_cursors))
                self._slice_cursors.pop(oldest_key, None)

            return HookResult(hook_type="callable", success=True)

        async def _session_end_cleanup(event: str, payload: dict[str, object]) -> Any:
            """Clean up slice cursor on session end + frustration-driven evolution."""
            from myrm_agent_harness.agent.hooks.types import HookResult

            session_id = str(payload.get("session_id", ""))
            self._slice_cursors.pop(session_id, None)

            # Frustration detection: scan conversation for style/behavior frustration
            messages = payload.get("messages")
            if messages and isinstance(messages, (list, tuple)) and len(messages) >= 2:
                from myrm_agent_harness.agent.skills.evolution.pipeline.frustration_detector import (
                    detect_frustration,
                )

                signal = detect_frustration(messages)
                if signal and self.queue:
                    logger.info(
                        "Frustration detected [%s]: '%s' — triggering DERIVED evolution",
                        signal.category,
                        signal.matched_text,
                    )
                    try:
                        await self.queue.enqueue(
                            EvolutionRequest(
                                evolution_type=EvolutionType.DERIVED,
                                skill_id=f"frustration_{signal.category}_{session_id[:8]}",
                                reason=f"User frustration [{signal.category}]: {signal.matched_text}",
                                user_feedback=signal.user_message[:500],
                                session_id=session_id,
                            ),
                            priority=QueuePriority.NORMAL,
                        )
                    except Exception as e:
                        logger.warning("Failed to enqueue frustration-driven evolution: %s", e)

            return HookResult(hook_type="callable", success=True)

        registry.register(
            HookEvent.TRACE_SLICE_READY,
            CallableHookDefinition(
                fn=_handle_trace_slice,
                block_on_failure=False,
            ),
        )
        registry.register(
            HookEvent.POST_TOOL_USE,
            CallableHookDefinition(
                fn=_window_counter,
                block_on_failure=False,
            ),
        )
        registry.register(
            HookEvent.SESSION_END,
            CallableHookDefinition(
                fn=_session_end_cleanup,
                block_on_failure=False,
            ),
        )

    async def record_execution(
        self,
        skill_id: str,
        success: bool,
        error_message: str = "",
    ) -> None:
        """Record a skill execution outcome into the quality ledger (framework hook).

        Business layer calls this after skill execution. Counting only: repair is
        driven by failure events and trace slices, never by this ledger.

        Args:
            skill_id: Executed skill ID
            success: Whether execution succeeded
            error_message: Error message if failed (logged, not persisted)
        """
        await self.tracker.record_execution(
            SkillExecutionResult(skill_id=skill_id, success=success, error_message=error_message)
        )

    async def evolve_skill(
        self, skill_id: str, evolution_type: EvolutionType, **kwargs: Any
    ) -> EvolutionProposal | None:
        """Manually trigger skill evolution.

        Args:
            skill_id: Skill to evolve
            evolution_type: Type of evolution
            **kwargs: Additional arguments (reason, user_feedback, etc.)

        Returns:
            EvolutionProposal or None if failed
        """
        if not self.engine:
            logger.error("Evolution engine not initialized (no LLM client)")
            return None

        # Apply screener if available
        if self.screener:
            request = EvolutionRequest(
                evolution_type=evolution_type,
                skill_id=skill_id,
                reason=kwargs.get("reason", ""),
                user_feedback=kwargs.get("user_feedback", ""),
                repeated_commands=kwargs.get("repeated_commands", []),
                force_retry=kwargs.get("force_retry", False),
            )
            screening_result = await self.screener.screen_request(request)
            if not screening_result.allowed:
                logger.info(
                    "Evolution for skill '%s' blocked by screener: %s",
                    skill_id,
                    screening_result.reason,
                )
                return None

        if evolution_type == EvolutionType.FIX:
            return await self.engine.fix_skill(skill_id, kwargs.get("reason", "Manual fix"))
        elif evolution_type == EvolutionType.DERIVED:
            return await self.engine.derive_skill_simple(skill_id, kwargs.get("user_feedback", ""))
        elif evolution_type == EvolutionType.SLICE_EXTRACTION:
            return await self.engine.extract_skill_from_slice(
                session_id=kwargs.get("session_id", ""),
                tool_call_ids=kwargs.get("tool_call_ids", []),
                agent_id=kwargs.get("agent_id"),
            )

        return None

    async def start_background_queue(self, on_proposal_callback: Any | None = None) -> None:
        """Start background evolution queue.

        Args:
            on_proposal_callback: Optional callback to notify GUI/Server when a proposal is ready.
        """
        if not self.queue:
            logger.warning("Background queue not enabled")
            return

        if not self.engine:
            logger.error("Cannot start queue without evolution engine")
            return

        # Set evolution handler
        async def evolution_handler(
            request: EvolutionRequest,
        ) -> EvolutionProposal | None:
            proposal = await self.evolve_skill(
                request.skill_id or "",
                request.evolution_type,
                reason=request.reason,
                user_feedback=request.user_feedback,
                repeated_commands=request.repeated_commands,
                session_id=request.session_id,
                tool_call_ids=request.tool_call_ids,
                agent_id=request.agent_id,
                force_retry=request.force_retry,
            )
            if proposal and on_proposal_callback:
                try:
                    import asyncio

                    if asyncio.iscoroutinefunction(on_proposal_callback):
                        await on_proposal_callback(proposal)
                    else:
                        on_proposal_callback(proposal)
                except Exception as e:
                    logger.error(f"Proposal callback failed: {e}")
            return proposal

        self.queue.set_evolution_handler(evolution_handler)
        await self.queue.start()
        logger.info("Background evolution queue started")

    async def stop_background_queue(self) -> None:
        """Stop background evolution queue."""
        if self.queue:
            await self.queue.stop()

    def get_stats(self) -> dict[str, Any]:
        """Get evolution statistics.

        Returns:
            Dict with all stats (metrics, queue)
        """
        stats: dict[str, Any] = {
            "metrics": self.metrics_tracker.get_report(),
        }

        if self.queue:
            stats["queue"] = self.queue.get_stats()

        return stats

    async def close(self) -> None:
        """Cleanup resources."""
        if self.queue:
            await self.stop_background_queue()

        self.store.close()
        logger.info("Evolution integration closed")


# Convenience function for business layer
def enable_skill_evolution(
    db_path: Path | str = ".myrm/skills_evolution.db",
    *,
    llm: BaseChatModel | None = None,
    context_pipeline: "ContextPipeline | None" = None,
    max_concurrent_evolutions: int = 5,
    event_log_backend: Any | None = None,
    evolution_strategy: str = "balanced",
    **kwargs: Any,
) -> EvolutionIntegration:
    """Enable skill evolution with one function call.

    Framework-provided convenience function for business layer.

    Args:
        db_path: Path to evolution database
        llm: LLM client for evolution (BaseChatModel)
        context_pipeline: Optional context management pipeline (auto-created if None)
        max_concurrent_evolutions: Max concurrent evolution tasks (default 5)
        event_log_backend: Optional backend for trace extraction.
        evolution_strategy: Controls screener behavior (balanced/innovate/harden/repair-only).
        **kwargs: Additional options (screener, enable_background_queue, etc.)

    Returns:
        EvolutionIntegration instance

    Example:
        ```python
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model="gpt-4")
        evolution = enable_skill_evolution(
            db_path=".myrm/skills.db",
            llm=llm,
            enable_background_queue=True,
            max_concurrent_evolutions=3,
            evolution_strategy="harden",
            event_log_backend=your_backend,
        )
        ```
    """
    return EvolutionIntegration(
        db_path,
        llm=llm,
        context_pipeline=context_pipeline,
        max_concurrent_evolutions=max_concurrent_evolutions,
        event_log_backend=event_log_backend,
        evolution_strategy=evolution_strategy,
        **kwargs,
    )
