"""Integration helpers for skill evolution system.

Makes it easy for business layer to enable evolution capabilities.
Framework provides the hooks, business layer decides when to use them.

[INPUT]
- agent.skills.evolution.core.types::EvolutionProposal, (POS: Data types for skill evolution system.)
- agent.skills.evolution.core.engine::SkillEvolutionEngine (POS: Skill evolution engine - Core of self-evolution system.)
- agent.skills.evolution.db.store::SkillStore (POS: SQLite persistence for skill evolution system.)
- toolkits.code_execution.executors.test_executor::SubprocessCodeExecutor (POS: Subprocess-based test execution for skill evolution TDE.)
- agent.skills.evolution.execution.tool_selector::EvolutionToolConfig (POS: Tool Selector for Evolution System)
- agent.skills.evolution.pipeline.analyzer::SkillExecutionAnalyzer (POS: Lightweight execution analysis for skill evolution decisions.)
- agent.skills.evolution.pipeline.screener::EvolutionScreener (POS: myrm_agent_harness/agent/skills/evolution/screener.py ## Architecture Two-phase screening to block "snowball effect" of blind fixes: **Phase 1: Rule-based (Cooldown)** Rejects repeated evolution attempts within cooldown period Checks both skill.updated_at and rejection history Zero LLM cost, instant response **Phase 2: LLM Confirmation (Cheap Model)** Only for FIX evolution type Analyzes real error logs (HTTP status, exception stack) Asks cheap LLM: "Is this really a skill code defect?" Returns YES (proceed) or NO + reason (block) **Prometheus Metrics (Observability)** evolution_screening_total: Counter by phase + result evolution_screening_confidence: Histogram of LLM confidence evolution_screening_duration_seconds: Histogram of screening duration by phase ## Design Principles 1. **Cost Optimization**: Use gpt-4o-mini/claude-haiku for Phase 2 2. **Fail-Safe**: LLM errors → Allow (don't block valid fixes) 3. **Transparency**: Record all rejections for audit 4. **Signal Extraction**: Focus on HTTP status + exception type vs full stack 5. **Observability**: Expose Prometheus metrics for monitoring and tuning)
- toolkits.retriever.embedding.cache::EmbeddingCache (POS: Embedding cache layer. Provides a two-tier caching mechanism (memory + SQLite) that sits between callers and the remote embedding API to avoid redundant calls.)
- agent.context_management.pipeline::ContextPipeline (POS: Message filter pipeline for composing multiple filters.)
- toolkits.code_execution::CodeExecutor (POS: Code execution toolkit entry point. Aggregates execution configuration, executor implementations, workspace management, and factory functions for the Agent-in-Sandbox architecture.)
- agent.skills.evolution::EvolutionIntegration (POS: Skill evolution engine - Core of self-evolution system.)
- toolkits.web_search::SearchServiceConfig (POS: Web search toolkit entry point. Aggregates and re-exports search tools, result types, metrics, and error hierarchy for unified import.)

[OUTPUT]
- EvolutionIntegration: All-in-one integration helper for skill evolution.
- get_global_evolution_integration: Get the global EvolutionIntegration instance if configured.
- set_global_evolution_integration: Set the global EvolutionIntegration instance.
- enable_skill_evolution: Enable skill evolution with one function call.

[POS]
Integration helpers for skill evolution system.
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
    SkillRecord,
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
from myrm_agent_harness.agent.skills.evolution.pipeline.analyzer import (
    SkillExecutionAnalyzer,
)
from myrm_agent_harness.agent.skills.evolution.pipeline.screener import (
    EvolutionScreener,
)
from myrm_agent_harness.toolkits.code_execution.executors.test_executor import (
    SubprocessCodeExecutor,
)
from myrm_agent_harness.toolkits.retriever.embedding.cache import (
    EmbeddingCache,
    get_embedding_cache,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.agent.context_management.pipeline import ContextPipeline
    from myrm_agent_harness.toolkits.code_execution import CodeExecutor
    from myrm_agent_harness.toolkits.web_search import SearchServiceConfig

    from .anti_loop_state import AntiLoopState

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
            llm_client=your_llm_client)

        # Record skill execution result
        await evolution.record_execution(skill_id="test", success=False, error="...")

        # Check for skills needing fix
        needs_fix = await evolution.get_skills_needing_fix()

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
        enable_embedding_cache: bool = True,
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
        vector_store: Any | None = None,
        embedding: Any | None = None,
        event_log_backend: Any | None = None,
    ):
        """Initialize evolution integration.

        Args:
            db_path: Path to SQLite database for skill storage
            llm: LLM client for evolution (BaseChatModel, business layer provides)
            context_pipeline: Optional context management pipeline (auto-created if None)
            enable_embedding_cache: Enable 2-layer embedding cache
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
        """
        self.db_path = Path(db_path)

        # Core components
        self.store = SkillStore(
            self.db_path,
            vector_store=vector_store,
            embedding=embedding,
        )
        self.tracker = SkillQualityTracker(self.store)
        self.analyzer = SkillExecutionAnalyzer()
        self.test_executor: SubprocessCodeExecutor | None = test_executor
        self.screener: EvolutionScreener | None = screener

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
                logger.debug(
                    "EvolutionIntegration: auto-created subprocess test executor"
                )

            self.engine = SkillEvolutionEngine(
                store=self.store,
                llm=llm,
                event_log_backend=event_log_backend,
                max_concurrent_evolutions=max_concurrent_evolutions,
            )

        # Optional components
        self.dependency_tracker = get_dependency_tracker()
        self.metrics_tracker = get_metrics_tracker()

        self.embedding_cache: EmbeddingCache | None = None
        if enable_embedding_cache:
            cache_path = self.db_path.parent / "embeddings.db"
            self.embedding_cache = get_embedding_cache(cache_path)
            if (
                embedding
                and hasattr(embedding, "_cache")
                and embedding._cache is None
            ):
                embedding._cache = self.embedding_cache
                logger.debug("Injected embedding_cache into provided embedding service")

        self.queue: EvolutionQueue | None = None
        if enable_background_queue:
            self.queue = get_evolution_queue(worker_count=queue_workers)

        logger.info(
            "Evolution integration initialized: db=%s, llm=%s, cache=%s, queue=%s",
            self.db_path,
            llm is not None,
            enable_embedding_cache,
            enable_background_queue,
        )

        # Register as global instance so middlewares can access it
        set_global_evolution_integration(self)

        # Inject trap lookup into skill loader for Known Pitfalls injection
        self._register_trap_lookup()

    def _register_trap_lookup(self) -> None:
        """Register trap lookup callback with SkillMdLoader for runtime injection."""
        try:
            from myrm_agent_harness.agent.skills.runtime.loader import skill_md_loader

            def _lookup_traps(skill_name: str) -> list[dict[str, Any]]:
                record = self.store.get_skill_by_name_version(skill_name)
                return record.traps if record else []

            skill_md_loader.set_trap_lookup(_lookup_traps)
            logger.debug("Trap lookup registered with SkillMdLoader")
        except Exception as e:
            logger.debug("Failed to register trap lookup (non-fatal): %s", e)

    def register_hooks(self, registry: Any) -> None:
        """Register framework hooks (e.g. TRACE_SLICE_READY) to the given session registry."""
        from myrm_agent_harness.agent.hooks.types import CallableHookDefinition, HookEvent

        async def _handle_trace_slice(event: str, payload: dict[str, object]) -> Any:
            from myrm_agent_harness.agent.hooks.types import HookResult
            session_id = str(payload.get("session_id", ""))

            tool_call_ids = payload.get("tool_call_ids", [])
            if not isinstance(tool_call_ids, list):
                tool_call_ids = []

            agent_id = payload.get("agent_id")
            agent_id = str(agent_id) if agent_id else None

            # Enqueue the extraction task to the background worker
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
                        priority=QueuePriority.LOW
                    )
                except Exception as e:
                    logger.warning("Failed to enqueue trace slice: %s", e)
            return HookResult(hook_type="callable", success=True)

        registry.register(
            HookEvent.TRACE_SLICE_READY,
            CallableHookDefinition(
                fn=_handle_trace_slice,
                block_on_failure=False,
            )
        )

    async def record_execution(
        self,
        skill_id: str,
        success: bool,
        error_message: str = "",
        context: dict[str, str] | None = None,
    ) -> None:
        """Record skill execution result (framework hook).

        Business layer calls this after skill execution.

        Args:
            skill_id: Executed skill ID
            success: Whether execution succeeded
            error_message: Error message if failed
            context: Optional execution context (e.g. {"task_intent": "..."})
        """
        # Auto-inject task_intent from ContextVar if not provided explicitly
        effective_context: dict[str, str] = dict(context) if context else {}
        if "task_intent" not in effective_context:
            from myrm_agent_harness.agent._skill_agent_context import get_task_intent

            intent = get_task_intent()
            if intent:
                effective_context["task_intent"] = intent

        result = SkillExecutionResult(
            skill_id=skill_id,
            success=success,
            error_message=error_message,
            context=effective_context,
        )

        metrics = await self.tracker.record_execution(result)

        # Error-Aware Smart Darwinian Quarantine & FIX Triggering
        needs_quarantine = False
        quarantine_reason = ""
        is_deterministic_error = False

        if not success and error_message:
            deterministic_errors = (
                # Python deterministic errors
                "SyntaxError",
                "IndentationError",
                "NameError",
                "TypeError",
                "ValueError",
                "AttributeError",
                "ModuleNotFoundError",
                "ImportError",
                "KeyError",
                "IndexError",
                "ZeroDivisionError",
                # System/Bash deterministic errors
                "command not found",
                "No such file or directory",
                "Permission denied",
            )
            if any(e in error_message for e in deterministic_errors):
                is_deterministic_error = True

        if not success:
            if is_deterministic_error:
                needs_quarantine = True
                quarantine_reason = "1-Strike (Deterministic Error)"
            elif metrics.consecutive_failures >= 3:
                needs_quarantine = True
                quarantine_reason = (
                    f"3-Strikes (Consecutive Failures: {metrics.consecutive_failures})"
                )

        if needs_quarantine:
            logger.error(
                "HARD QUARANTINE: Skill %s deactivated. Reason: %s. Error: %s",
                skill_id,
                quarantine_reason,
                (
                    error_message.split("\n")[-1][:100]
                    if "\n" in error_message
                    else error_message[:100]
                ),
            )
            await self.store.deactivate_skill(skill_id)

        # Auto-trigger FIX if needed (business layer can override this)
        # CRITICAL: We MUST trigger FIX if the skill was quarantined (even if it's the 1st failure),
        # OR if the standard metrics say so.
        if (needs_quarantine or metrics.should_trigger_fix()) and self.engine:
            logger.warning(
                "Skill %s needs FIX: success_rate=%.2f, consecutive_failures=%d, quarantined=%s",
                skill_id,
                metrics.success_rate,
                metrics.consecutive_failures,
                needs_quarantine,
            )

            # Enqueue to background or execute immediately
            if self.queue:
                priority = (
                    QueuePriority.CRITICAL
                    if is_deterministic_error
                    else (
                        QueuePriority.HIGH
                        if metrics.consecutive_failures < 3
                        else QueuePriority.CRITICAL
                    )
                )
                await self.queue.enqueue(
                    EvolutionRequest(
                        evolution_type=EvolutionType.FIX,
                        skill_id=skill_id,
                        reason=error_message,
                    ),
                    priority=priority,
                )
            else:
                # Immediate fix (blocking)
                logger.info("Immediate FIX evolution for %s", skill_id)
                await self.engine.fix_skill(skill_id, error_message)

    async def get_skills_needing_fix(self) -> list[SkillRecord]:
        """Get skills that need FIX evolution.

        Returns:
            List of skill records needing fix
        """
        return await self.tracker.get_skills_needing_fix()

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
            return await self.engine.fix_skill(
                skill_id, kwargs.get("reason", "Manual fix")
            )
        elif evolution_type == EvolutionType.DERIVED:
            return await self.engine.derive_skill_simple(
                skill_id, kwargs.get("user_feedback", "")
            )
        elif evolution_type == EvolutionType.CAPTURED:
            return await self.engine.capture_skill_simple(
                kwargs.get("repeated_commands", []),
                user_confirmed=kwargs.get("user_confirmed", False),
            )
        elif evolution_type == EvolutionType.SLICE_EXTRACTION:
            return await self.engine.extract_skill_from_slice(
                session_id=kwargs.get("session_id", ""),
                tool_call_ids=kwargs.get("tool_call_ids", []),
                agent_id=kwargs.get("agent_id"),
            )

        return None

    async def run_evidence_evolution(
        self,
        on_proposal_callback: Any | None = None,
        lookback_days: int = 7,
    ) -> list[EvolutionProposal]:
        """Run evidence-based evolution for all skills with sufficient evidence.

        Aggregates recent execution data, then evolves each skill that has
        enough success+failure evidence. Designed to be called as an idle task.

        Args:
            on_proposal_callback: Optional callback for each generated proposal.
            lookback_days: Days of execution history to analyze (default 7).

        Returns:
            List of generated EvolutionProposals.
        """
        if not self.engine:
            logger.error("Evidence evolution: no engine (LLM not configured)")
            return []

        from myrm_agent_harness.agent.skills.evolution.pipeline.evidence_aggregator import (
            EvidenceAggregator,
        )

        aggregator = EvidenceAggregator(self.store, lookback_days=lookback_days)
        evidence_groups = aggregator.aggregate()

        proposals: list[EvolutionProposal] = []
        for evidence in evidence_groups:
            if not evidence.has_sufficient_evidence():
                continue

            try:
                proposal = await self.engine.evolve_from_evidence(evidence)
                if proposal:
                    proposals.append(proposal)
                    if on_proposal_callback:
                        import asyncio as _asyncio

                        if _asyncio.iscoroutinefunction(on_proposal_callback):
                            await on_proposal_callback(proposal)
                        else:
                            on_proposal_callback(proposal)
            except Exception as e:
                logger.error(
                    "Evidence evolution failed for skill '%s': %s",
                    evidence.skill_name,
                    e,
                    exc_info=True,
                )

        logger.info(
            "Evidence evolution completed: %d proposals from %d eligible skills",
            len(proposals),
            sum(1 for g in evidence_groups if g.has_sufficient_evidence()),
        )
        return proposals

    async def start_background_queue(
        self, on_proposal_callback: Any | None = None
    ) -> None:
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
            Dict with all stats (metrics, queue, cache)
        """
        stats: dict[str, Any] = {
            "metrics": self.metrics_tracker.get_report(),
        }

        if self.queue:
            stats["queue"] = self.queue.get_stats()

        if self.embedding_cache:
            stats["cache"] = self.embedding_cache.get_stats()

        return stats

    async def close(self) -> None:
        """Cleanup resources."""
        if self.queue:
            await self.stop_background_queue()

        if self.embedding_cache:
            self.embedding_cache.close()

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
        **kwargs: Additional options (enable_embedding_cache, screener, etc.)

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
            max_concurrent_evolutions=3,  # Limit to 3 concurrent evolutions
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
        **kwargs,
    )
