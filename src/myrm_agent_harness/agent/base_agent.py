"""Base Agent — lightweight agent with streaming, token tracking, and artifacts.

Runtime helpers (middleware, tools, guards) live in ``_internals.agent_runtime``.
Recovery strategies (overflow, failover, diagnostics) live in ``_internals.agent_recovery``.
Lifecycle helpers (workspace setup, cleanup, post-processing) live in ``_internals.run_lifecycle``.

[INPUT]
- utils.chat_utils::ChatHistoryReq (POS: Agent)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)
- utils.runtime.cancellation::CancellationToken (POS: Agent  ContextVar  BaseAgent)
- utils.runtime.steering::SteeringToken (POS: Steering  Agent  Agent)

[OUTPUT]
- BaseAgent: Lightweight agent base class with streaming events, token...

[POS]
Base Agent — lightweight agent with streaming, token tracking, and artifacts.
"""

import copy
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.types import Command

from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
from myrm_agent_harness.agent.tool_management import ToolRegistry
from myrm_agent_harness.utils.chat_utils import ChatHistoryReq
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ._internals.langgraph_guard import (
    apply_langgraph_tool_args_guard as _apply_langgraph_tool_args_guard,
)
from .streaming.channel_output_hints import resolve_channel_output_hint
from .streaming.message_builder import build_messages
from .streaming.model_discipline import resolve_escalation_contract, resolve_execution_discipline
from .streaming.utils import DATETIME_SYSTEM_RULES
from .sub_agents.manager import SubagentManager, SubagentTask
from .sub_agents.types import SubagentConfig, SubAgentResult
from .types import AgentRunStatistics, AgentRuntimeConfig

if TYPE_CHECKING:
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import BaseMessage
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.agent.deep_research import DeepResearchConfig
    from myrm_agent_harness.agent.deep_research.orchestrator import (
        ClarifyCallback,
        CycleCallback,
        PlanCallback,
    )
    from myrm_agent_harness.agent.extensions.protocols import AgentExtension
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.toolkits.llms.consensus.types import (
        ConsensusConfig,
        ConsensusResult,
    )
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken
    from myrm_agent_harness.utils.runtime.steering import SteeringToken
    from myrm_agent_harness.utils.token_economics.budget_guard import BudgetChecker

logger = get_agent_logger(__name__)

_apply_langgraph_tool_args_guard()


class BaseAgent:
    """Lightweight agent base class with streaming events, token tracking, and artifacts.

    Template-method hooks for subclass customization:
    ``_build_middlewares``, ``_build_tools``, ``_prepare_context``.
    """

    ArtifactReadyHandler = Callable[[dict[str, object]], Awaitable[dict[str, object] | None]]

    def __init__(
        self,
        llm: BaseChatModel,
        executor: "CodeExecutor | None" = None,
        middlewares: "list[AgentMiddleware[Any, Any]] | None" = None,
        system_prompt: str | None = None,
        tools: list[BaseTool] | None = None,
        discoverable_tools: list[BaseTool] | None = None,
        context_schema: type | None = None,
        config: AgentRuntimeConfig | None = None,
        on_artifacts_ready: "ArtifactReadyHandler | None" = None,
        fallback_llm: BaseChatModel | None = None,
        safety_fallback_llm: BaseChatModel | None = None,
        escalation_target_llm: BaseChatModel | None = None,
        checkpointer: "BaseCheckpointSaver | None" = None,
        event_log_backend: EventLogBackend | None = None,
        model_resolver: object | None = None,
    ) -> None:
        self.llm = llm
        self.fallback_llm = fallback_llm
        self.safety_fallback_llm = safety_fallback_llm
        self.escalation_target_llm = escalation_target_llm
        self.executor = executor
        self.user_middlewares = middlewares or []
        self.system_prompt = system_prompt
        self.user_tools = tools or []
        self.discoverable_tools = discoverable_tools or []
        self.context_schema = context_schema
        self.config = config or AgentRuntimeConfig()
        self.on_artifacts_ready = on_artifacts_ready
        self.checkpointer = checkpointer
        self.event_log_backend = event_log_backend
        self.model_resolver = model_resolver
        self._agent = None
        self._cached_tools: list[BaseTool] | None = None
        self._cached_system_prompt: str | None = None
        self._cached_middlewares: list[AgentMiddleware[Any, Any]] | None = None
        self._failover_used = False
        self._last_run_stats: AgentRunStatistics | None = None
        self._last_context: dict[str, object] = {}
        self._subagent_manager = SubagentManager(self)
        self._is_running = False
        self._extensions: list[AgentExtension] = []
        self.budget_checker: BudgetChecker | None = None

        # Tool lifecycle management
        from myrm_agent_harness.agent.tool_management import ToolLifecycleManager

        self._lifecycle_manager = ToolLifecycleManager()
        self._tools_initialized = False
        self._tool_registry = self._create_registry()

    def register_extension(self, ext: "AgentExtension") -> None:
        """Register an AgentExtension. Must be called before the first ``run()``.

        Raises ``ValueError`` if an extension with the same name is already registered,
        or if the agent graph has already been built (``_ensure_initialized`` was called).
        """
        if self._agent is not None:
            raise ValueError(
                f"Cannot register extension '{ext.name}' after agent initialization. "
                "Call register_extension() before the first run()."
            )
        existing_names = {e.name for e in self._extensions}
        if ext.name in existing_names:
            raise ValueError(f"Extension name conflict: '{ext.name}' is already registered.")
        self._extensions.append(ext)

    async def _ensure_initialized(self) -> None:
        if self._agent is not None:
            return

        # 10/10 Scheme: If system_prompt is explicitly empty string (""), we are in FORK context mode.
        # We must NOT append DATETIME_SYSTEM_RULES to prevent creating a new SystemMessage that breaks Prefix Cache.
        if self.system_prompt == "":
            self._cached_system_prompt = None
        else:
            from myrm_agent_harness.agent.middlewares._session_context import (
                set_canary_token,
            )
            from myrm_agent_harness.agent.security.detection.canary_guard import (
                build_canary_instruction,
                generate_canary,
            )

            canary = generate_canary()
            set_canary_token(canary)
            from myrm_agent_harness.toolkits.code_execution.platform import detect_platform

            self._cached_system_prompt = (
                (self.system_prompt or "")
                + DATETIME_SYSTEM_RULES
                + resolve_execution_discipline(self.llm)
                + resolve_escalation_contract(self.llm, self.escalation_target_llm)
                + resolve_channel_output_hint(self.config.channel_name)
                + detect_platform().environment_prompt_line
                + build_canary_instruction(canary)
            )

        self._cached_middlewares = self._build_middlewares()
        self._cached_tools = await self._build_tools()

        from myrm_agent_harness.agent.middlewares._session_context import (
            set_active_resolved_tools,
            set_active_tool_registry,
        )

        set_active_tool_registry(self._tool_registry)
        if self._cached_tools is not None:
            set_active_resolved_tools(self._cached_tools)

        for ext in self._extensions:
            ext_tools = ext.get_tools()
            if ext_tools:
                self._cached_tools.extend(ext_tools)
            ext_mws = ext.get_middlewares()
            if ext_mws:
                self._cached_middlewares.extend(ext_mws)

        if self._extensions:
            from myrm_agent_harness.agent.tool_management.tool_layers import (
                ToolLayer,
                get_tool_layer,
            )

            self._cached_tools.sort(key=lambda t: (get_tool_layer(t.name) or ToolLayer.EXTENDED, t.name))

        logger.debug("BaseAgent: final tools=%s", [t.name for t in self._cached_tools])

        llm = self._apply_parallel_tool_calls(self.llm)

        self._agent = create_agent(
            model=llm,
            tools=self._cached_tools,
            system_prompt=self._cached_system_prompt,
            middleware=cast(list["AgentMiddleware[Any, Any]"], self._cached_middlewares),
            context_schema=self.context_schema,
            checkpointer=self.checkpointer,
        )

        for ext in self._extensions:
            try:
                await ext.on_agent_init(self)
            except Exception:
                logger.exception("Extension '%s' on_agent_init failed", ext.name)

        # Fire-and-forget: pre-warm Anthropic/Qwen server-side prefix cache
        # while the user is still typing their first message.
        from myrm_agent_harness.agent.context_management.preheat import schedule_init_preheat

        model_name = getattr(llm, "model_name", "") or getattr(llm, "model", "") or ""
        schedule_init_preheat(llm, self._cached_system_prompt, model_name)

    def _rebuild_agent_with_llm(self, new_llm: BaseChatModel) -> None:
        """Rebuild agent graph with a different LLM for failover."""
        from ._internals.agent_recovery import rebuild_agent_with_llm

        rebuild_agent_with_llm(self, new_llm)

    def add_tools(self, tools: list[BaseTool]) -> None:
        """Dynamically add tools after initialization and rebuild the agent graph.

        Use for tools that require a fully initialized agent instance
        (e.g. delegate_task needs a reference to the parent agent).

        Note:
            If any of the new tools are lifecycle-aware (have ainit/acleanup),
            they will be initialized on the next run() call.
        """
        from myrm_agent_harness.agent.streaming.utils import normalize_tool_names
        from myrm_agent_harness.agent.tool_management.tool_layers import (
            ToolLayer,
            get_tool_layer,
        )
        from myrm_agent_harness.agent.tool_management.types import ToolSource

        normalized = normalize_tool_names(tools)
        for tool in normalized:
            self._tool_registry.register(tool, source=ToolSource.USER)

        if self._cached_tools is None:
            self.user_tools.extend(normalized)
            self.user_tools.sort(key=lambda t: (get_tool_layer(t.name) or ToolLayer.EXTENDED, t.name))
            return

        self._cached_tools.extend(normalized)
        # Enforce Cache Tiering: sort tools by ToolLayer to protect prompt cache prefixes
        self._cached_tools.sort(key=lambda t: (get_tool_layer(t.name) or ToolLayer.EXTENDED, t.name))

        # Mark tools as needing re-initialization (lifecycle-aware tools will be init'd on next run)
        # LifecycleManager.initialize_tools() is idempotent (skips already-initialized tools)
        self._tools_initialized = False

        llm = self._apply_parallel_tool_calls(self.llm)
        self._agent = create_agent(
            model=llm,
            tools=self._cached_tools,
            system_prompt=self._cached_system_prompt,
            middleware=cast(list["AgentMiddleware[Any, Any]"], self._cached_middlewares),
            context_schema=self.context_schema,
            checkpointer=self.checkpointer,
        )

    def _apply_parallel_tool_calls(self, llm: BaseChatModel) -> BaseChatModel:
        """Inject parallel_tool_calls into bind_tools if configured."""
        if self.config.parallel_tool_calls is None:
            return llm

        original_bind_tools = llm.bind_tools
        parallel = self.config.parallel_tool_calls

        def patched_bind_tools(tools: Sequence[dict[str, Any] | type | BaseTool | Any], **kwargs: Any) -> Any:
            kwargs.setdefault("parallel_tool_calls", parallel)
            return original_bind_tools(tools, **kwargs)

        wrapped = copy.copy(llm)
        # Pydantic models reject __setattr__ for non-field names;
        # bypass via object.__setattr__ to patch the method.
        object.__setattr__(wrapped, "bind_tools", patched_bind_tools)
        return wrapped

    @staticmethod
    def _init_usage_ledger(context: dict[str, object] | None) -> None:
        """Attach a UsageLedger to the current request scope."""
        from ._internals.agent_runtime import init_usage_ledger

        init_usage_ledger(context)

    def _build_middlewares(self) -> list[Any]:
        """Build the middleware chain. Override in subclasses for customization."""
        from ._internals.agent_runtime import build_middlewares

        return build_middlewares(self._tool_registry, self.user_middlewares, self.config.engine_params)

    def _create_registry(self) -> ToolRegistry:
        """Create a fresh ToolRegistry for this build cycle."""
        from ._internals.agent_runtime import create_registry

        return create_registry()

    def _emit_tools_snapshot(self) -> list[dict[str, object]] | None:
        """Serializable tools snapshot. Subclasses override ``get_tool_snapshot()``."""
        from ._internals.agent_runtime import emit_tools_snapshot

        return emit_tools_snapshot(self._tool_registry)

    async def _build_tools(self) -> list[BaseTool]:
        """Build tool list via ToolRegistry (user + middleware sources)."""
        from ._internals.agent_runtime import build_tools

        return await build_tools(
            self._tool_registry,
            self.user_tools,
            self.discoverable_tools,
            self._cached_middlewares,
        )

    @property
    def is_initialized(self) -> bool:
        return self._agent is not None

    @property
    def last_run_stats(self) -> AgentRunStatistics | None:
        return self._last_run_stats

    async def run(
        self,
        query: str | list[dict[str, Any]] | Command[Any],
        chat_history: ChatHistoryReq | list["BaseMessage"] | None = None,
        message_id: str | None = None,
        context: dict[str, Any] | None = None,
        cancel_token: "CancellationToken | None" = None,
        steering_token: "SteeringToken | None" = None,
        timezone: str | None = None,
    ) -> AsyncGenerator[dict[str, object]]:
        """Stream agent events. Supports normal query and Command(resume=...) modes."""
        from myrm_agent_harness.agent.errors.agent_errors import AgentBusyError

        if self._is_running:
            raise AgentBusyError("Agent is already running a task. Please wait for it to complete.")

        self._is_running = True

        from myrm_agent_harness.infra.tracing import get_tracer

        tracer = get_tracer("agent.run")
        try:
            span = tracer.start_span("agent.run")
            span.set_attribute("agent.type", type(self).__name__)
            if message_id:
                span.set_attribute("agent.message_id", message_id)
            query_text = query if isinstance(query, str) else str(query)[:200]
            span.set_attribute("agent.query", query_text)

            try:
                async for event in self._run_internal(
                    query=query,
                    chat_history=chat_history,
                    message_id=message_id,
                    context=context,
                    cancel_token=cancel_token,
                    steering_token=steering_token,
                    timezone=timezone,
                ):
                    yield event
                span.set_attribute("agent.status", "completed")
            except Exception as exc:
                span.set_attribute("agent.status", "error")
                span.set_attribute("error.type", type(exc).__name__)
                span.record_exception(exc)
                raise
            finally:
                span.end()
        finally:
            self._is_running = False

    async def _run_internal(
        self,
        query: str | list[dict[str, Any]] | Command[Any],
        chat_history: ChatHistoryReq | list["BaseMessage"] | None = None,
        message_id: str | None = None,
        context: dict[str, Any] | None = None,
        cancel_token: "CancellationToken | None" = None,
        steering_token: "SteeringToken | None" = None,
        timezone: str | None = None,
    ) -> AsyncGenerator[dict[str, object]]:
        """Core execution loop. Delegates to ``_internals.agent_runtime.run_agent_loop``."""
        await self._ensure_initialized()

        from ._internals.agent_runtime import run_agent_loop

        async for event in run_agent_loop(
            agent_state=self,
            query=query,
            chat_history=chat_history,
            message_id=message_id,
            context=context,
            cancel_token=cancel_token,
            steering_token=steering_token,
            timezone=timezone,
        ):
            yield event

    async def _setup_workspace(self, context: dict[str, object] | None, message_id: str) -> dict[str, object]:
        """Create workspace, bind executor, and set context vars."""
        from ._internals.run_lifecycle import setup_workspace

        merged_ctx, _ = await setup_workspace(self.executor, context)
        return merged_ctx

    async def _prepare_context(self, context: dict[str, object]) -> dict[str, object]:
        """Hook for subclasses to enrich context (e.g. skill paths). No-op by default."""
        return context

    @property
    def _children(self) -> Mapping[str, SubagentTask]:
        return self._subagent_manager.children

    @property
    def _children_results(self) -> Mapping[str, SubAgentResult]:
        return self._subagent_manager.child_results

    async def _spawn_child(
        self,
        task_id: str,
        agent_type: str,
        task_description: str,
        config: SubagentConfig,
        context: dict[str, object],
        tool_registry_getter: Callable[[], list[BaseTool]],
        wait: bool,
        parent_type: str | None = None,
        cancel_token: "CancellationToken | None" = None,
        resume_command: object | None = None,
        complexity_tier: str | None = None,
    ) -> SubAgentResult | dict[str, object]:
        return await self._subagent_manager.spawn_child(
            task_id=task_id,
            agent_type=agent_type,
            task_description=task_description,
            config=config,
            context=context,
            tool_registry_getter=tool_registry_getter,
            wait=wait,
            parent_type=parent_type,
            cancel_token=cancel_token,
            resume_command=resume_command,
            complexity_tier=complexity_tier,
        )

    def list_children(self) -> list[dict[str, object]]:
        return self._subagent_manager.list_children()

    def cancel_child(self, task_id: str) -> bool:
        return self._subagent_manager.cancel_child(task_id)

    def cancel_all_children(self) -> int:
        return self._subagent_manager.cancel_all()

    def steer_child(self, task_id: str, message: str) -> bool:
        return self._subagent_manager.steer_child(task_id, message)

    async def wait_children(
        self,
        task_ids: list[str],
        min_success_rate: float = 0.5,
        timeout: float | None = None,
    ) -> dict[str, object]:
        return await self._subagent_manager.wait_children(task_ids, min_success_rate=min_success_rate, timeout=timeout)

    async def trigger_async_wakeup(self, result: SubAgentResult) -> None:
        """Trigger an async wakeup event for the parent agent.

        This is called by SubagentManager when a background child task completes
        (either started with wait=False, or wait=True that returned via non-fatal timeout).
        It uses the global wakeup registry to notify the Server layer (e.g. Gateway/Runner)
        to trigger a new run, while also pushing to the progress sink if active.
        """
        from myrm_agent_harness.agent.streaming.types import AgentEventType
        from myrm_agent_harness.utils.runtime.progress_sink import (
            get_tool_progress_sink,
        )
        from myrm_agent_harness.utils.runtime.wakeup_registry import (
            get_global_wakeup_handler,
        )

        session_id = None
        agent_id = "unknown"
        if self._last_context:
            session_id = self._last_context.get("session_id")
            agent_id = str(self._last_context.get("agent_id", "unknown"))

        # 1. Notify global handler (for actual background wakeup)
        handler = get_global_wakeup_handler()
        if handler:
            try:
                await handler.on_async_wakeup(result, agent_id, session_id)
                logger.info(f"Triggered global wakeup handler for subagent {result.task_id} (session_id={session_id})")
            except Exception as e:
                logger.error(f"Global wakeup handler failed: {e}")

        # 2. Push to active SSE stream (if any)
        sink = get_tool_progress_sink()
        if sink:
            try:
                await sink.emit(
                    {
                        "type": AgentEventType.ASYNC_WAKEUP.value,
                        "data": {
                            "task_id": result.task_id,
                            "agent_type": result.agent_type,
                            "success": result.success,
                            "agent_id": agent_id,
                            "session_id": session_id,
                        },
                    }
                )
            except Exception as e:
                logger.error(f"Failed to emit ASYNC_WAKEUP: {e}")

    async def run_deep_research(
        self,
        query: str,
        chat_history: ChatHistoryReq | list["BaseMessage"] | None = None,
        message_id: str | None = None,
        context: dict[str, Any] | None = None,
        cancel_token: "CancellationToken | None" = None,
        config: "DeepResearchConfig | None" = None,
        on_clarify: "ClarifyCallback | None" = None,
        on_plan_ready: "PlanCallback | None" = None,
        on_cycle_complete: "CycleCallback | None" = None,
    ) -> AsyncGenerator[dict[str, object]]:
        """Run Deep Research mode — multi-phase orchestrated research.

        Delegates to DeepResearchOrchestrator, sharing this agent's LLM and tools.
        The orchestrator manages its own lifecycle (clarify → plan → research → report)
        independently from the normal LangGraph agent loop.

        Args:
            on_clarify: Async callback for clarification (``AskQuestionInput`` → answer string/list/dict | None).
            on_plan_ready: Async callback to review/modify the research plan (str → str | None).
            on_cycle_complete: Async callback after each research cycle (cycle, results → PhaseGuidance | None).
        """
        from myrm_agent_harness.agent.deep_research import (
            DeepResearchConfig,
            DeepResearchOrchestrator,
        )

        await self._ensure_initialized()
        message_id = message_id or str(uuid4())

        merged_context = await self._setup_workspace(context, message_id)

        from langchain_core.messages import BaseMessage as LCBaseMessage

        lc_history: list[LCBaseMessage] | None = None
        if chat_history:
            lc_history = build_messages("", chat_history)[:-1] if chat_history else None

        orchestrator = DeepResearchOrchestrator(
            llm=self.llm,
            config=config or DeepResearchConfig(),
            parent_tools=self._cached_tools if self._cached_tools else self.user_tools,
            cancel_token=cancel_token,
            context=merged_context,
            executor=self.executor,
            on_clarify=on_clarify,
            on_plan_ready=on_plan_ready,
            on_cycle_complete=on_cycle_complete,
        )

        async for event in orchestrator.run(
            query=query,
            chat_history=lc_history,
            message_id=message_id,
            context=merged_context,
        ):
            yield event

    async def run_consensus(
        self,
        query: str,
        reference_llms: list[BaseChatModel] | None = None,
        aggregator_llm: BaseChatModel | None = None,
        config: "ConsensusConfig | None" = None,
        cancel_token: "CancellationToken | None" = None,
    ) -> "ConsensusResult":
        """Run Mixture-of-Agents consensus inference.

        Queries multiple reference LLMs in parallel, then synthesises all
        responses through an aggregator LLM.  Falls back to a single-model
        answer when consensus requirements are not met.

        When *reference_llms* is ``None``, the main ``self.llm`` is used as a
        single reference (effectively a no-op pass-through).  The business
        layer is expected to supply real reference models.

        Args:
            query: the user question.
            reference_llms: LLM instances to query in parallel.
            aggregator_llm: LLM used to synthesise all answers.
            config: optional ``ConsensusConfig`` override.
            cancel_token: optional cancellation token to abort early.
        """
        from myrm_agent_harness.toolkits.llms.consensus import (
            ConsensusConfig,
            ConsensusEngine,
        )

        refs = reference_llms or [self.llm]
        agg = aggregator_llm or self.llm
        engine = ConsensusEngine(
            reference_llms=refs,
            aggregator_llm=agg,
            config=config or ConsensusConfig(),
        )
        return await engine.run(query, system_prompt=self.system_prompt, cancel_token=cancel_token)

    async def get_checkpoint_state(self, thread_id: str) -> dict[str, object]:
        """Extract complete execution state for checkpoint save.

        Delegates to ``_internals.run_lifecycle.extract_checkpoint_state``.
        """
        from ._internals.run_lifecycle import extract_checkpoint_state

        return await extract_checkpoint_state(
            checkpointer=self.checkpointer,
            last_context=self._last_context,
            last_run_stats=self._last_run_stats,
            thread_id=thread_id,
        )

    async def restore_checkpoint_state(self, checkpoint_data: dict[str, object]) -> None:
        """Restore execution state from checkpoint data.

        Restores messages to the checkpointer and runtime context to the agent.
        Symmetric with ``get_checkpoint_state()``.

        Args:
            checkpoint_data: Dict with keys: messages, variables, progress, last_tool.
        """
        from .sub_agents.checkpoint.state_extractor import restore_subagent_state

        await restore_subagent_state(self, checkpoint_data)

    async def cleanup_tools(self) -> None:
        """Cleanup all lifecycle-aware tools.

        This method should be called when the agent is being terminated to properly
        release resources (e.g., close database connections, stop file watchers).

        Note:
            - This is best-effort: cleanup failures are logged but don't raise
            - Safe to call multiple times (idempotent)
            - Automatically called by Business/Control Plane layers on agent termination

        Usage (Business layer):
            try:
                async for event in agent.run(query, context=...):
                    yield event
            finally:
                await agent.cleanup_tools()
        """
        for ext in self._extensions:
            try:
                await ext.on_agent_shutdown(self)
            except Exception:
                logger.exception("Extension '%s' on_agent_shutdown failed", ext.name)
        if self._cached_tools:
            await self._lifecycle_manager.cleanup_tools(self._cached_tools)
