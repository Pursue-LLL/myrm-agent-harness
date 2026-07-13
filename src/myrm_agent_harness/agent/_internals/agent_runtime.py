"""Agent runtime — core execution loop, middleware chain, tool building.

Contains ``run_agent_loop()`` (the full ``BaseAgent._run_internal`` body)
and helper functions that ``BaseAgent`` delegates to.

[INPUT]
- agent.meta_tools.file_ops.observers.snapshot_observer::set_current_message_id (POS: Binds per-turn assistant message id so file snapshots and cumulative diffs are isolated per user round.)
- agent.middlewares.approval::ToolApprovalMiddleware (POS: Approval queue helpers. Handles AnyMemory ↔ PendingRecord conversion for the approval pipeline. Internal only — not part of the public API.)
- agent.artifacts::ArtifactContextManager (POS: Provides ArtifactType, ArtifactMappings, is_active_content.)
- agent.event_log.logger::EventLogger (POS: Integration façade. Injected into BaseAgent via ``event_log_backend`` param. Async-buffered writes ensure zero impact on the event production hot path.)
- agent.middlewares.completion_guard::CompletionGuard (POS: Fills the "Agent finishing" gap in the guard chain. Existing guards cover tool-call loops (LoopGuard), context overflow (ContextBudgetGuard), and emergency stops (EStop). CompletionGuard ensures the Agent verifies its work before delivering a final answer.)
- agent.middlewares.security_boundary_middleware::SecurityBoundaryMiddleware (POS: Security boundary middleware.)
- agent.middlewares.security_guardrail_middleware::SecurityGuardrailMiddleware (POS: Security guardrail middleware.)
- agent.streaming.source_tracker::SourceTracker (POS: BaseAgent  SourceTracker)
- agent.streaming.stream_executor::STREAM_DONE, (POS: Agent Agent  StreamRecoveryMixin)
- agent.streaming.types::AgentEventType (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.tool_management::ToolRegistry, (POS: Orchestrates tool lifecycle: initialize_tools() -> cleanup_tools() Implements best-effort cleanup, rollback on init failure, and thread-safe operations.)
- agent.types::AgentRunStatistics (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.base_agent::BaseAgent (POS: Base Agent — lightweight agent with streaming, token tracking, and artifacts.)
- utils.chat_utils::ChatHistoryReq (POS: Agent)
- utils.runtime.cancellation::CancellationToken (POS: Agent  ContextVar  BaseAgent)
- utils.runtime.steering::SteeringToken (POS: Steering  Agent  Agent)
- agent.middlewares.replan_middleware::ReplanMiddleware (POS: Dynamic Replan Loop Middleware.)
- agent.meta_tools.discover_capability.discover_capability_tool::create_discover_capability_tool (POS: Unified Capability Discovery meta-tool. Facade pattern that searches BOTH native discoverable tools (ToolRegistry) and external skills (SkillSearchEngine).)
- agent.tool_management.types::ToolSnapshot (POS: Core types for the tool management subsystem. ToolSource tracks provenance; ToolEntry bundles a tool with its source and layer. ToolSnapshot provides a serializable view of resolved tools for API exposure.)
- utils.token_economics.usage_ledger::UsageLedger (POS: LLM  JSONL)

[OUTPUT]
- build_middlewares: Build the full middleware chain for a BaseAgent.
- create_registry: Create a fresh ToolRegistry for one build cycle.
- build_tools: Build the resolved tool list via ToolRegistry.
- emit_tools_snapshot: Return a serialisable tools snapshot or ``None`` if empty.
- init_usage_ledger: Attach a ``UsageLedger`` to the current request scope.

[POS]
Agent runtime — core execution loop, middleware chain, tool building.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from contextlib import nullcontext
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command

from myrm_agent_harness.agent.artifacts import ArtifactContextManager
from myrm_agent_harness.agent.event_log.logger import EventLogger
from myrm_agent_harness.agent.middlewares.approval import (
    set_agent_id,
    set_approval_session,
    set_event_logger,
    set_security_config,
)
from myrm_agent_harness.agent.streaming.source_tracker import SourceTracker
from myrm_agent_harness.agent.streaming.stream_executor import (
    STREAM_DONE,
    StreamContext,
    StreamExecutor,
)
from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.agent.streaming.utils import (
    set_user_timezone,
    validate_context,
)
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.llms.errors.classifier import classify_error
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.cancellation import set_cancel_token
from myrm_agent_harness.utils.runtime.progress_sink import (
    create_queue_sink,
    set_tool_progress_sink,
)
from myrm_agent_harness.utils.runtime.steering import set_steering_token
from myrm_agent_harness.utils.token_economics.tracker import init_token_tracker

from ._agent_build import build_middlewares, build_tools, create_registry, emit_tools_snapshot
from ._agent_helpers import (
    _fire_and_forget,
    extract_query_text,
    init_usage_ledger,
    reset_all_guards,
    schedule_post_run_idle_tasks,
)
from .run_lifecycle import cleanup_run, collect_tracker_stats, compute_context_budget_snapshot, post_run_events

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentState
    from langchain_core.messages import BaseMessage

    from myrm_agent_harness.agent.base_agent import BaseAgent
    from myrm_agent_harness.utils.chat_utils import ChatHistoryReq
    from myrm_agent_harness.utils.runtime.cancellation import CancellationToken
    from myrm_agent_harness.utils.runtime.steering import SteeringToken

logger = get_agent_logger(__name__)

# Re-export for backward compatibility
__all__ = [
    "build_middlewares",
    "build_tools",
    "create_registry",
    "emit_tools_snapshot",
    "extract_query_text",
    "init_usage_ledger",
    "reset_all_guards",
    "run_agent_loop",
    "schedule_post_run_idle_tasks",
]


# ============================================================================
# Core Agent Loop
# ============================================================================


async def run_agent_loop(
    agent_state: BaseAgent,
    query: str | list[dict[str, Any]] | Command[Any],
    chat_history: ChatHistoryReq | list[BaseMessage] | None,
    message_id: str,
    context: dict[str, object] | None,
    cancel_token: CancellationToken | None,
    steering_token: SteeringToken | None,
    timezone: str | None,
) -> AsyncGenerator[dict[str, object]]:
    """Core agent execution loop — the full ``BaseAgent._run_internal`` body."""
    from myrm_agent_harness.agent.streaming.message_builder import (
        build_messages,
        inject_datetime_tags,
        inject_ephemeral_quote,
    )

    message_id = message_id or str(uuid4())
    start_time = time.time()
    is_resume = isinstance(query, Command)
    reset_all_guards(
        is_resume=is_resume,
        graph_recursion_limit=agent_state.config.recursion_limit,
    )

    # Align SnapshotStore / DiffCollector with this assistant turn (server message id).
    # Without this, ContextVar keeps the first auto-generated msg_* across runs and
    # get_initial_file_snapshot() returns an older CREATE row for the same path.
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        set_current_message_id,
    )

    set_current_message_id(message_id)

    if agent_state.config.collect_artifacts:
        artifact_ctx_manager: ArtifactContextManager | nullcontext[None] = ArtifactContextManager(message_id=message_id)
    else:
        artifact_ctx_manager = nullcontext()

    async with artifact_ctx_manager:
        _run_tracker = init_token_tracker(budget_checker=agent_state.budget_checker)

        from myrm_agent_harness.agent.context_management.infra.cache_break_detector import (
            init_cache_break_detector,
        )

        init_cache_break_detector()

        if steering_token:
            set_steering_token(steering_token)
        if timezone:
            set_user_timezone(timezone)

        set_security_config(agent_state.config.security_config)
        from myrm_agent_harness.agent.middlewares._session_context import (
            set_active_message_id,
        )

        set_active_message_id(message_id)
        session_key = str(context.get("approval_session_key") or context.get("session_id") or "") if context else ""
        from myrm_agent_harness.agent.artifacts.ui_registry import bind_run_message_id

        if session_key:
            bind_run_message_id(session_key, message_id)
        set_approval_session(session_key)

        # Make sure agent_id is populated from config
        set_agent_id(agent_state.config.agent_id)

        output_queue: asyncio.Queue[dict[str, object] | object] = asyncio.Queue()

        merged_context = await agent_state._setup_workspace(context, message_id)
        agent_state._last_context = merged_context
        agent_state._init_usage_ledger(merged_context)

        from myrm_agent_harness.agent.middlewares._mutation_verifier import (
            reset_mutation_state,
        )

        reset_mutation_state()

        # Add locale to merged_context for diagnostic generation
        if agent_state.config.locale:
            merged_context["locale"] = agent_state.config.locale

        # Initialize lifecycle-aware tools (once per agent instance)
        if not agent_state._tools_initialized and agent_state._cached_tools:
            run_config_for_init: dict[str, object] = {
                "configurable": {
                    "context": merged_context,
                },
            }
            try:
                await agent_state._lifecycle_manager.initialize_tools(
                    agent_state._cached_tools,
                    run_config_for_init,  # type: ignore[arg-type]
                )
                agent_state._tools_initialized = True
            except Exception:
                logger.exception(" [Lifecycle] Tool initialization failed, agent startup aborted")
                raise

        event_logger: EventLogger | None = None
        session_id = str(merged_context.get("session_id", message_id))
        if agent_state.event_log_backend is not None:
            event_logger = EventLogger(
                agent_state.event_log_backend,
                session_id,
                agent_id=str(merged_context.get("agent_id", "")) or None,
                task_type=str(merged_context.get("task_type", "")) or None,
            )
            await event_logger.start()

        set_event_logger(event_logger)

        from myrm_agent_harness.core.context_vars import prompt_routing_key_var

        prompt_routing_key_var.set(session_id)

        from myrm_agent_harness.agent.middlewares._session_context import (
            set_active_resolved_tools,
            set_active_tool_registry,
        )

        set_active_tool_registry(agent_state._tool_registry)
        if agent_state._cached_tools is not None:
            set_active_resolved_tools(agent_state._cached_tools)

        # Initialize ToolCallBroadcaster hooks for observability.
        # skill_agent.run() has its own hook init, but the streaming path
        # (agent_runtime → StreamExecutor → astream) bypasses it.
        from myrm_agent_harness.agent.hooks import (
            bootstrap_hook_registry,
            get_hook_executor,
        )
        from myrm_agent_harness.agent.streaming.broadcast.tool_call_broadcaster import (
            register_to_hook_registry as register_broadcaster,
        )

        existing_executor = get_hook_executor()
        if existing_executor:
            hook_registry = existing_executor.registry
        else:
            hook_registry = bootstrap_hook_registry()
            register_broadcaster(hook_registry, event_logger)

        stats = AgentRunStatistics()

        query_text = extract_query_text(query)

        # Store current query as task intent for skill evolution context
        from myrm_agent_harness.agent._skill_agent_context import set_task_intent

        set_task_intent(str(query_text)[:500])

        # Emit USER_TURN hook for auto-capture
        from myrm_agent_harness.agent.hooks.types import HookEvent

        hook_exec = existing_executor or get_hook_executor()
        if hook_exec is not None:
            _fire_and_forget(
                hook_exec.execute(
                    HookEvent.USER_TURN, {"user_input": str(query_text), "session_id": session_key or message_id}
                )
            )

        logger.step("Agent started")
        query_preview = str(query_text)[:100]
        logger.info("Query: %s%s", query_preview, "..." if len(str(query_text)) > 100 else "")

        tools_snapshot = agent_state._emit_tools_snapshot()
        if tools_snapshot is not None:
            yield {
                "type": AgentEventType.TOOLS_SNAPSHOT.value,
                "data": tools_snapshot,
                "messageId": message_id,
            }

        yield {
            "type": AgentEventType.TASKS_STEPS.value,
            "step_key": "analyzing_query",
            "tool_name": None,
            "messageId": message_id,
        }

        if cancel_token and cancel_token.is_cancelled:
            stats.was_cancelled = True
            agent_state._last_run_stats = stats
            logger.warning(f" 启动前被取消: reason={cancel_token.cancel_reason}")
            yield {
                "type": AgentEventType.CANCELLED.value,
                "data": "Cancelled before start",
                "messageId": message_id,
            }
            cleanup_run(
                stats,
                start_time,
                cancel_token,
                steering_token,
                agent_state.cancel_all_children,
                merged_context=merged_context,
            )
            return

        thread_id = session_key or message_id

        # Intercept approval text before processing query
        from myrm_agent_harness.agent.middlewares.approval_interception import (
            intercept_approval_text,
        )

        try:
            query = await intercept_approval_text(
                query=query,
                checkpointer=agent_state.checkpointer,
                thread_id=thread_id,
                message_id=message_id,
                output_queue=output_queue,
            )
        except Exception as e:
            logger.warning(f"Approval text interception failed: {e}")

        is_resume = isinstance(query, Command)
        agent_input: Command[Any] | AgentState[Any]

        if is_resume:
            agent_input = cast("Command[Any] | AgentState[Any]", query)
            logger.info(f" Resume: {query.resume if hasattr(query, 'resume') else query}")
            # Prompt Cache preservation: Mark as Resume
            merged_context["is_resume"] = True
            merged_context = validate_context(merged_context, agent_state.context_schema)
            merged_context = await agent_state._prepare_context(merged_context)
        else:
            messages = build_messages(query, chat_history)
            inject_datetime_tags(messages, chat_history, query)

            quote_raw = merged_context.get("quote_attachment")
            if quote_raw is not None and messages:
                from langchain_core.messages import HumanMessage

                from myrm_agent_harness.agent.types import QuoteAttachment

                if isinstance(messages[-1], HumanMessage):
                    if isinstance(quote_raw, QuoteAttachment):
                        messages[-1].additional_kwargs["quote_attachment"] = quote_raw
                    elif (
                        isinstance(quote_raw, dict) and "source_message_id" in quote_raw and "quoted_text" in quote_raw
                    ):
                        messages[-1].additional_kwargs["quote_attachment"] = QuoteAttachment(
                            source_message_id=str(quote_raw["source_message_id"]),
                            quoted_text=str(quote_raw["quoted_text"]),
                        )

            inject_ephemeral_quote(messages)

            from langchain_core.messages import HumanMessage

            from myrm_agent_harness.agent.file_snapshot.restore_inbox import (
                drain_restore_notifications,
            )
            from myrm_agent_harness.agent.sub_agents.notifications import (
                format_active_subagent_context,
            )

            restore_notice = drain_restore_notifications()
            if restore_notice:
                messages.append(HumanMessage(content=restore_notice))
                logger.info(
                    " Injected file-restore notification (%d chars)",
                    len(restore_notice),
                )

            stale_notifications = agent_state._subagent_manager.drain_notifications()
            if stale_notifications:
                messages.append(HumanMessage(content=stale_notifications))
                logger.info(
                    " Injected %d char of stale subagent notification(s)",
                    len(stale_notifications),
                )

            active_ctx = format_active_subagent_context(agent_state._subagent_manager.list_children())
            if active_ctx:
                messages.append(HumanMessage(content=active_ctx))
                logger.info(
                    " Injected active subagent context (%d chars)",
                    len(active_ctx),
                )

            merged_context = validate_context(merged_context, agent_state.context_schema)
            merged_context = await agent_state._prepare_context(merged_context)

            agent_input = cast("AgentState[Any]", {"messages": messages})

        # Strip non-serializable callbacks before LangGraph checkpoint (passed via StreamContext).
        goal_provider = merged_context.pop("goal_provider", None)
        on_goal_terminal = merged_context.pop("on_goal_terminal", None)
        on_loop_restart = merged_context.pop("on_loop_restart", None)
        from myrm_agent_harness.agent.middlewares._session_context import set_goal_provider

        set_goal_provider(goal_provider)

        # --- Goal Planning Interception ---
        if goal_provider and not is_resume:
            try:
                from myrm_agent_harness.agent.goals.goal_interceptor import (
                    intercept_goal_and_plan,
                )
                from myrm_agent_harness.toolkits.storage.local import (
                    LocalStorageBackend,
                )

                # Use LocalStorageBackend directly with workspace_root
                workspace_root_path = str(merged_context.get("workspace_root", "/tmp"))
                storage_provider = LocalStorageBackend(workspace_root_path)

                if storage_provider:
                    await intercept_goal_and_plan(
                        goal_provider=goal_provider,
                        session_id=session_id,
                        query=query,
                        llm=agent_state.llm,
                        storage_provider=storage_provider,
                    )
            except Exception as e:
                logger.warning(f"Goal planning interception failed: {e}")

        run_config: RunnableConfig = {
            "recursion_limit": agent_state.config.recursion_limit,
            "configurable": {
                "context": merged_context,
                "thread_id": thread_id,
            },
        }

        # 动态注入可视化追踪 Callback (如果开启)
        tracing_config = getattr(agent_state.config, "tracing_config", None)
        if tracing_config and getattr(tracing_config, "enable_local_ui", False):
            try:
                from openinference.instrumentation.langchain import (
                    LangChainInstrumentor,
                )

                LangChainInstrumentor().instrument()
                logger.info("Phoenix tracing instrumented successfully.")
            except (ImportError, TypeError):
                logger.warning(
                    "Phoenix is not installed or broken. Please install with `pip install myrm-agent-harness[observability]`"
                )

        assert agent_state._agent is not None

        # Extract LLM metadata for precise error diagnostics
        llm_info: dict[str, str | None] | None = None
        if agent_state.llm:
            # `model_name` on LangChain/LiteLLM may exist but be None; still prefer `model` when so.
            model_name = getattr(agent_state.llm, "model_name", None) or getattr(agent_state.llm, "model", None)
            base_url = getattr(agent_state.llm, "base_url", None)
            if model_name:
                llm_info = {
                    "model_name": str(model_name),
                    "base_url": str(base_url) if base_url else None,
                }

        def _drain_teammate_messages() -> str | None:
            from myrm_agent_harness.agent.coordination.mailbox import (
                drain_teammate_messages_for_task,
            )
            from myrm_agent_harness.agent.middlewares._session_context import (
                get_subagent_task_id,
            )

            task_id = get_subagent_task_id()
            if not task_id:
                return None
            sid = str(merged_context.get("session_id") or session_id or "")
            return drain_teammate_messages_for_task(sid, task_id)

        ctx = StreamContext(
            agent=agent_state._agent,
            agent_input=agent_input,
            merged_context=merged_context,
            run_config=run_config,
            stats=stats,
            message_id=message_id,
            cancel_token=cancel_token,
            steering_token=steering_token,
            source_tracker=SourceTracker(),
            output_queue=output_queue,
            event_logger=event_logger,
            drain_subagent_notifications=agent_state._subagent_manager.drain_notifications,
            drain_teammate_messages=_drain_teammate_messages,
            llm_info=llm_info,
            goal_provider=goal_provider,
            on_goal_terminal=on_goal_terminal,
            on_loop_restart=on_loop_restart,
            escalation_target_llm=getattr(agent_state, "escalation_target_llm", None),
            llm=agent_state.llm,
            token_tracker=_run_tracker,
        )
        executor = StreamExecutor(
            ctx,
            agent_state.fallback_llm,
            agent_state.safety_fallback_llm,
            agent_state._rebuild_agent_with_llm,
            agent_state._failover_used,
        )

        set_tool_progress_sink(create_queue_sink(output_queue, message_id))
        set_cancel_token(cancel_token)
        try:
            task = asyncio.create_task(executor.execute())

            while True:
                event = await output_queue.get()
                if event is STREAM_DONE:
                    break
                yield cast("dict[str, object]", event)

            await task
            agent_state._failover_used = executor.failover_used

        except Exception as e:
            from .agent_recovery import diagnose_llm_error

            error_msg, diagnostic_dict = diagnose_llm_error(e, agent_state.llm, agent_state.config.locale)
            error_type = type(e).__name__

            if not stats.error_message:
                stats.error_message = f"{error_type}: {error_msg}"
                logger.error(
                    "Outer loop exception — %s: %s",
                    error_type,
                    error_msg[:300],
                    exc_info=True,
                )
                error_kind = classify_error(e)
                error_event = {
                    "type": AgentEventType.ERROR.value,
                    "error": error_msg,
                    "error_type": error_type,
                    "error_kind": error_kind.value,
                    "messageId": message_id,
                }
                # Add diagnostic_result if available
                if diagnostic_dict:
                    error_event["diagnostic_result"] = diagnostic_dict
                yield error_event

        finally:
            if event_logger is not None:
                try:
                    await event_logger.close()
                except Exception:
                    logger.debug("EventLogger close error", exc_info=True)

            # If goal is present in context, use its max_tokens as max_ctx
            goal_dict = merged_context.get("goal")
            if isinstance(goal_dict, dict) and "max_tokens" in goal_dict and goal_dict["max_tokens"]:
                max_ctx = goal_dict["max_tokens"]
            else:
                max_ctx = merged_context.get("max_context_tokens") if merged_context else None

            stats.context_budget = compute_context_budget_snapshot(stats, int(max_ctx) if max_ctx is not None else None)
            agent_state._last_run_stats = stats

        # Collect token stats BEFORE post_run_events so message_end includes usage.
        collect_tracker_stats(stats, tracker=_run_tracker)

        # Artifacts must be collected before cleanup_run clears the executor.
        async for event in post_run_events(
            stats,
            message_id,
            merged_context,
            agent_state.config.collect_artifacts,
            agent_state.on_artifacts_ready,
        ):
            yield event

        cleanup_run(
            stats,
            start_time,
            cancel_token,
            steering_token,
            agent_state.cancel_all_children,
            merged_context=merged_context,
        )

        if not stats.was_cancelled:
            logger.info(
                "Agent execution completed; final answer streaming %s",
                "completed" if executor.streaming_final_answer else "not detected",
            )
        usage_info = f", tokens: {stats.token_usage.total_tokens}" if stats.token_usage else ""
        cost_info = f", cost: ${stats.cost_usd:.6f}" if stats.cost_usd > 0 else ""
        logger.info(
            "Execution stats [duration: %.2fs, nodes: %d, tool_calls: %d, msg_chunks: %d%s%s]",
            stats.total_duration_seconds,
            stats.node_execution_count,
            stats.tool_call_count,
            stats.message_chunk_count,
            usage_info,
            cost_info,
        )

        schedule_post_run_idle_tasks(merged_context)
