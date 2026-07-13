"""Agent run lifecycle helpers — workspace setup, cleanup, and post-processing.

Stateless functions used by BaseAgent.run() for workspace creation,
run-end cleanup (ContextVar resets, token stats collection), and
post-processing event emission.

[INPUT]
- agent.streaming.types::ContextBudgetSnapshot (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- agent.types::AgentRunStatistics, (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)
- toolkits.code_execution.workspace.storage_root_bind (POS: ContextVar binding for aggregate workspace filesystem roots during a single agent Task.)
- utils.runtime.steering::SteeringToken (POS: Steering  Agent  Agent)

[OUTPUT]
- setup_workspace: Create workspace under host ``workspaces_storage_root``, bind executor, set context vars. The storage-root ContextVar undo token is stashed in a ContextVar (not in ``merged_context``) so checkpoints/msgpack never serialize it.
- cleanup_run: Run-end cleanup: cancel children, reset context vars, col...
- compute_context_budget_snapshot: Compute a lightweight context budget snapshot from token ...
- post_run_events: Yield post-processing events: artifacts and MESSAGE_END.
- serialize_message: Serialize a LangChain message to a plain dict.

[POS]
Agent run lifecycle helpers — workspace setup, cleanup, and post-processing.
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Callable
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    clear_pending_explicit_cache_snapshot,
    install_llm_response_hook,
)
from myrm_agent_harness.agent.event_log.llm_observability import (
    install_llm_observability_hook,
)
from myrm_agent_harness.agent.middlewares.approval import set_workspace_root
from myrm_agent_harness.agent.streaming.types import ContextBudgetSnapshot
from myrm_agent_harness.agent.types import (
    AgentRunStatistics,
    WorkspaceBinding,
    map_to_completion_status,
)
from myrm_agent_harness.toolkits.code_execution import create_workspace_service
from myrm_agent_harness.toolkits.code_execution.workspace.storage_root_bind import (
    bind_workspace_storage_root,
    release_workspace_storage_bind_token,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.runtime.cancellation import set_cancel_token
from myrm_agent_harness.utils.runtime.progress_sink import set_tool_progress_sink
from myrm_agent_harness.utils.token_economics.tracker import (
    get_token_tracker,
    reset_token_tracker,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor
    from myrm_agent_harness.utils.runtime.steering import SteeringToken
    from myrm_agent_harness.utils.token_economics.tracker import TokenTracker

logger = get_agent_logger(__name__)

install_llm_response_hook()
install_llm_observability_hook()

_WS_BIND_CTX_KEY = "__workspace_storage_bind_token"  # legacy; never serialize — see _workspace_bind_handle_stash

_workspace_bind_handle_stash: ContextVar[object | None] = ContextVar("workspace_bind_handle_stash", default=None)


def _stash_workspace_bind_handle(handle: object) -> None:
    _workspace_bind_handle_stash.set(handle)


def _take_workspace_bind_handle() -> object | None:
    handle = _workspace_bind_handle_stash.get()
    _workspace_bind_handle_stash.set(None)
    return handle


def _init_pseudonym_store(workspace_path: str) -> None:
    """Initialize PseudonymStore if the privacy policy uses PSEUDONYMIZE."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_privacy_policy,
        set_pseudonym_store,
    )
    from myrm_agent_harness.agent.security.types import PIIAction

    policy = get_privacy_policy()
    if not policy.enabled:
        return
    needs_store = policy.s2_action == PIIAction.PSEUDONYMIZE or policy.s3_action == PIIAction.PSEUDONYMIZE
    if not needs_store:
        return

    from myrm_agent_harness.agent.security.detection.pseudonym_store import (
        get_pseudonym_store,
    )

    db_path = str(Path(workspace_path).parent / "pseudonym_store.db")
    store = get_pseudonym_store(db_path)
    set_pseudonym_store(store)
    logger.info("PseudonymStore initialized at %s", db_path)

    _register_pii_pseudonymizer(policy, store)


def _register_pii_pseudonymizer(policy: object, store: object) -> None:
    """Build and register a PII pseudonymization closure for memory_scanner."""
    from myrm_agent_harness.core.security.detection.pii_classifier import classify_content
    from myrm_agent_harness.core.security.detection.pseudonymizer import pseudonymize_text
    from myrm_agent_harness.core.security.types import PIIAction, PrivacyPolicy, SensitivityLevel
    from myrm_agent_harness.toolkits.memory._internal.memory_scanner import set_pii_pseudonymizer

    if not isinstance(policy, PrivacyPolicy):
        return

    def _pseudonymize(text: str) -> str:
        if not policy.enabled:
            return text
        has_pseudonymize = policy.s2_action == PIIAction.PSEUDONYMIZE or policy.s3_action == PIIAction.PSEUDONYMIZE
        if not has_pseudonymize or store is None:
            return text

        pii_result = classify_content(text, policy)
        if pii_result.level == SensitivityLevel.S1:
            return text

        levels_to_process: list[SensitivityLevel] = [pii_result.level]
        if pii_result.level == SensitivityLevel.S3 and policy.s2_action == PIIAction.PSEUDONYMIZE:
            levels_to_process.append(SensitivityLevel.S2)

        result = text
        total_count = 0
        for level in levels_to_process:
            action = policy.s3_action if level == SensitivityLevel.S3 else policy.s2_action
            if action != PIIAction.PSEUDONYMIZE:
                continue
            ps_result = pseudonymize_text(result, store, level)
            if ps_result.count > 0:
                result = ps_result.text
                total_count += ps_result.count

        if total_count > 0:
            logger.warning("[MEMORY_SCAN] Pseudonymized %d PII items in memory content", total_count)
        return result

    set_pii_pseudonymizer(_pseudonymize)


async def setup_workspace(
    executor: CodeExecutor | None, context: dict[str, object] | None
) -> tuple[dict[str, object], CodeExecutor]:
    """Create workspace, bind executor, and set context vars.

    Returns:
        (merged_context, executor) — context now contains workspace_path.
    """
    if context is None:
        context = {}

    ws_root_raw = context.get("workspaces_storage_root")
    if ws_root_raw is None or isinstance(ws_root_raw, bool):
        raise ValueError(
            "workspaces_storage_root is required (absolute filesystem root containing "
            "`workspaces/`). Host layer must set merged_context.workspaces_storage_root."
        )
    ws_storage_text = str(ws_root_raw).strip()
    if not ws_storage_text:
        raise ValueError("workspaces_storage_root must not be empty.")
    agg_root = Path(ws_storage_text).expanduser().resolve()
    bind_handle = bind_workspace_storage_root(agg_root)
    _stash_workspace_bind_handle(bind_handle)

    binding: WorkspaceBinding | None = context.get("workspace_binding")  # type: ignore

    if binding and binding.root_path:
        # Explicit binding from AgentRuntimeSpec
        workspace_path = binding.root_path
        if binding.mode == "chat" and binding.chat_id:
            # We don't append chat_id here because Server already did it in storage.service
            pass
        elif binding.mode == "background" and binding.task_id:
            import os

            workspace_path = os.path.join(workspace_path, "jobs", binding.task_id)

        import os

        os.makedirs(workspace_path, exist_ok=True)
    else:
        # Resolve via WorkspaceService under the host-provided aggregate root
        raw_session_id = context.get("session_id")
        if not raw_session_id:
            raise ValueError(
                "workspace_binding with root_path, or session_id with workspaces_storage_root, "
                "is required — business layer supplies session_id (e.g., chat_<id>)."
            )

        session_id = str(raw_session_id)
        workspace_svc = create_workspace_service(root_dir=agg_root)
        workspace = await workspace_svc.get_or_create(session_id=session_id)
        workspace_path = workspace_svc.get_workspace_absolute_path(workspace)

    try:
        if executor is None:
            from myrm_agent_harness.toolkits.code_execution import create_executor

            try:
                executor = create_executor()
                logger.debug(f" Auto-created Executor: {executor.get_executor_name()}")
            except Exception as e:
                logger.error(f" Failed to create Executor: {e}")
                raise
        else:
            logger.debug(f" Using provided Executor: {executor.get_executor_name()}")

        executor.bind_workspace(workspace_path)
        logger.debug(f" {executor.get_executor_name()}: workspace bound to {workspace_path}")

        from myrm_agent_harness.toolkits.code_execution.executors.base import (
            set_executor,
        )

        set_executor(executor)
        set_workspace_root(workspace_path)
        _init_pseudonym_store(workspace_path)

        from myrm_agent_harness.agent.workspace_rules.tracker import (
            init_subdirectory_tracker,
        )

        init_subdirectory_tracker(workspace_path)
        context["workspace_path"] = workspace_path

        from myrm_agent_harness.toolkits.code_execution.executors.base import (
            stash_executor_for_session,
        )

        session_id = str(context.get("session_id", ""))
        if session_id:
            stash_executor_for_session(session_id, executor)

        from myrm_agent_harness.observability.metrics.agent_metrics import record_ttfa_run_start

        record_ttfa_run_start()

    except Exception:
        leaked = _take_workspace_bind_handle()
        release_workspace_storage_bind_token(leaked)
        raise

    return context, executor


def cleanup_run(
    stats: AgentRunStatistics,
    start_time: float,
    cancel_token: object | None,
    steering_token: SteeringToken | None,
    cancel_all_fn: Callable[[], int],
    *,
    merged_context: dict[str, object] | None = None,
) -> None:
    """Run-end cleanup: cancel children, reset context vars, collect stats.

    Args:
        stats: Mutable statistics object to fill.
        start_time: ``time.time()`` captured at run start.
        cancel_token: Active cancellation token (will be cleared).
        steering_token: Active steering token (will be cleared if set).
        cancel_all_fn: Callable to cancel all child subagents.
        merged_context: Run context carrying workspace bind token resets.
    """
    try:
        stashed = _take_workspace_bind_handle()
        legacy: object | None = None
        if merged_context is not None:
            legacy = merged_context.pop(_WS_BIND_CTX_KEY, None)
        for t in (stashed, legacy):
            release_workspace_storage_bind_token(t)

        cancelled_count = cancel_all_fn()
        if cancelled_count > 0:
            logger.info(f" Cancelled {cancelled_count} running subagents on parent cleanup")

        set_tool_progress_sink(None)
        set_cancel_token(None)
        if steering_token:
            from myrm_agent_harness.utils.runtime.steering import set_steering_token

            set_steering_token(None)
        from myrm_agent_harness.agent.middlewares.approval import (
            set_event_logger,
            set_security_config,
        )

        set_security_config(None)
        from myrm_agent_harness.agent.artifacts.ui_registry import pop_run_message_id
        from myrm_agent_harness.agent.middlewares._session_context import get_approval_session

        pop_run_message_id(get_approval_session())
        set_workspace_root("")
        set_event_logger(None)
        from myrm_agent_harness.agent.middlewares._session_context import set_goal_provider

        set_goal_provider(None)

        from myrm_agent_harness.agent.workspace_rules.tracker import (
            reset_subdirectory_tracker,
        )

        reset_subdirectory_tracker()

        from myrm_agent_harness.agent.middlewares._session_context import (
            set_pseudonym_store,
        )

        set_pseudonym_store(None)

        from myrm_agent_harness.toolkits.memory._internal.memory_scanner import set_pii_pseudonymizer

        set_pii_pseudonymizer(None)

        from myrm_agent_harness.toolkits.code_execution.executors.base import (
            clear_stashed_executor,
            set_executor,
        )

        set_executor(None)

        if merged_context:
            cleanup_session_id = str(merged_context.get("session_id", ""))
            if cleanup_session_id:
                clear_stashed_executor(cleanup_session_id)

        collect_tracker_stats(stats)

        # Record Prometheus metrics
        from myrm_agent_harness.observability.metrics.registry import metrics_registry

        if metrics_registry.enabled:
            agent_type = "base_agent"  # Can be passed if needed, but we'll use a generic one here
            duration_s = time.time() - start_time
            metrics_registry.record_execution(
                agent_id=agent_type,
                duration_s=duration_s,
                status="success" if not stats.was_cancelled else "cancelled",
            )

            if stats.model_usage:
                for model, usage in stats.model_usage.items():
                    metrics_registry.record_tokens(
                        agent_id=agent_type,
                        model=model,
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )

        reset_token_tracker()
        clear_pending_explicit_cache_snapshot()

        stats.total_duration_seconds = time.time() - start_time
    except Exception as cleanup_error:
        logger.error(f"Error during cleanup: {cleanup_error}", exc_info=True)


def collect_tracker_stats(stats: AgentRunStatistics, *, tracker: "TokenTracker | None" = None) -> None:
    """Extract token usage and cost from the current TokenTracker into stats.

    Args:
        stats: Mutable stats object to populate.
        tracker: Explicit tracker reference. Falls back to ContextVar lookup if None.
                 Needed because async generators lose ContextVar state across yields.
    """
    if tracker is None:
        tracker = get_token_tracker()
    if not tracker:
        return

    stats.token_usage = tracker.get_usage()
    stats.cost_usd = tracker.total_cost_usd
    stats.cost_status = tracker.cost_status
    stats.completion_status = map_to_completion_status(tracker.last_finish_reason)

    if tracker.model_usage:
        stats.model_usage = {
            model: {
                **mu.to_dict(),
                "cost_usd": round(tracker.model_cost.get(model, 0.0), 6),
            }
            for model, mu in tracker.model_usage.items()
        }
        stats.primary_model = max(tracker.model_usage, key=lambda m: tracker.model_usage[m].total_tokens)

    if tracker.usage.cached_tokens > 0:
        cache_stats = tracker.usage.get_cache_effectiveness()
        logger.info(
            f" [Session Cache Summary] "
            f"Calls: {tracker.call_count} | "
            f"Hit Rate: {cache_stats['cache_hit_rate']:.1%} | "
            f"Cost Savings: {cache_stats['cost_savings_pct']:.1%} "
            f"({cache_stats['cost_savings_absolute']:.0f} tokens)"
        )

    if tracker.total_cost_usd > 0:
        logger.warning(
            f" [Session Cost] ${tracker.total_cost_usd:.6f} ({tracker.call_count} calls, {tracker.error_count} errors)"
        )


def compute_context_budget_snapshot(
    stats: AgentRunStatistics, max_context_tokens: int | None
) -> ContextBudgetSnapshot | None:
    """Compute a lightweight context budget snapshot from token tracker stats.

    Uses actual prompt_tokens from the last LLM call (provider-reported,
    more accurate than character-based estimation).

    usage_percent is relative to max_context_tokens (user-facing percentage).
    health_status: healthy (<80%), warning (80-90%), critical (>=90%).
    """

    if not stats.token_usage or not stats.token_usage.last_call:
        return None

    last_prompt = stats.token_usage.last_call.prompt_tokens
    if last_prompt <= 0:
        return None

    max_ctx = max_context_tokens if max_context_tokens and max_context_tokens > 0 else 128_000
    usage_pct = (last_prompt / max_ctx) * 100

    if usage_pct >= 90:
        health = "critical"
    elif usage_pct >= 80:
        health = "warning"
    else:
        health = "healthy"

    return ContextBudgetSnapshot(
        current_tokens=last_prompt,
        max_context_tokens=max_ctx,
        usage_percent=usage_pct,
        health_status=health,
    )


async def post_run_events(
    stats: AgentRunStatistics,
    message_id: str,
    merged_context: dict[str, object],
    collect_artifacts: bool,
    on_artifacts_ready: object | None,
) -> AsyncGenerator[dict[str, object]]:
    """Yield post-processing events: artifacts and MESSAGE_END."""
    if stats.was_cancelled:
        return

    if collect_artifacts and on_artifacts_ready:
        from myrm_agent_harness.agent.streaming.artifact_events import (
            emit_artifacts_ready_event,
        )

        async for raw_event in emit_artifacts_ready_event(message_id, merged_context):
            processed = await on_artifacts_ready(raw_event)  # type: ignore[operator]
            if processed:
                yield processed

    from myrm_agent_harness.agent.streaming.artifact_events import collect_ui_artifacts
    from myrm_agent_harness.agent.streaming.types import AgentEventType

    async for event in collect_ui_artifacts(message_id):
        yield event

    # File Mutation Verifier — emit failure event before MESSAGE_END
    from myrm_agent_harness.agent.middlewares._mutation_verifier import (
        format_mutation_failures,
    )

    mutation_payload = format_mutation_failures()
    if mutation_payload:
        yield {
            "type": AgentEventType.FILE_MUTATION_FAILED.value,
            "data": mutation_payload,
            "messageId": message_id,
        }

    message_end_event: dict[str, object] = {
        "type": AgentEventType.MESSAGE_END.value,
        "data": "",
        "messageId": message_id,
        "completion_status": stats.completion_status.value,
    }
    if stats.token_usage:
        usage_dict = stats.token_usage.to_dict()
        if stats.model_usage:
            usage_dict["model_usage"] = stats.model_usage
        message_end_event["usage"] = usage_dict

    try:
        from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

        tracker = get_token_tracker()
        if tracker is not None:
            message_end_event["token_economics"] = tracker.to_dict()
    except Exception:
        pass

    if stats.cost_usd > 0:
        message_end_event["cost_usd"] = round(stats.cost_usd, 6)
        message_end_event["cost_status"] = stats.cost_status
    if stats.primary_model:
        message_end_event["model"] = stats.primary_model
    if stats.context_budget:
        message_end_event["context_budget"] = stats.context_budget.to_dict()

    if tracker is not None and tracker.budget_checker is not None:
        remaining = tracker.budget_checker.get_remaining_budget()
        if remaining is not None:
            budget_status = tracker.last_budget_status
            if budget_status in ("warning", "exceeded"):
                message_end_event["usage_alert"] = {
                    "status": budget_status,
                    "today_cost": round(tracker.total_cost_usd, 6),
                    "remaining": round(remaining, 6),
                }
    yield message_end_event


# ============================================================================
# Checkpoint State Extraction
# ============================================================================


def serialize_message(msg: object) -> dict[str, object]:
    """Serialize a LangChain message to a plain dict."""
    if hasattr(msg, "dict"):
        return msg.dict()
    if hasattr(msg, "to_json"):
        return msg.to_json()
    return {"type": "unknown", "content": str(msg)}


async def extract_checkpoint_state(
    checkpointer: BaseCheckpointSaver[str] | None,
    last_context: dict[str, object] | None,
    last_run_stats: AgentRunStatistics | None,
    thread_id: str,
) -> dict[str, object]:
    """Extract complete execution state for checkpoint save.

    Used by ``BaseAgent.get_checkpoint_state()`` and subagent checkpoint extraction.

    Args:
        checkpointer: LangGraph BaseCheckpointSaver (or None).
        last_context: Agent's last runtime context dict.
        last_run_stats: Most recent run statistics.
        thread_id: LangGraph thread ID for checkpointer lookup.

    Returns:
        Dict with keys: messages, context, stats, progress, last_tool.
    """
    messages: list[dict[str, object]] = []
    raw_context = dict(last_context or {})
    raw_context.pop(_WS_BIND_CTX_KEY, None)
    context: dict[str, object] = raw_context
    stats: dict[str, object] = {}
    progress = 0.0
    last_tool: str | None = None

    if checkpointer is not None:
        try:
            checkpoint_config = {"configurable": {"thread_id": thread_id}}
            checkpoint = await checkpointer.aget(checkpoint_config)

            if checkpoint and "messages" in checkpoint.channel_values:
                raw_messages = checkpoint.channel_values["messages"]
                messages = [serialize_message(msg) for msg in raw_messages]

                for msg in reversed(messages):
                    if msg.get("type") == "ai" and msg.get("tool_calls"):
                        tool_calls = msg.get("tool_calls", [])
                        if tool_calls and isinstance(tool_calls, list):
                            last_tool = tool_calls[-1].get("name")
                            break

                logger.debug(
                    "Extracted %d messages from checkpointer (last_tool=%s)",
                    len(messages),
                    last_tool,
                )
        except Exception as e:
            logger.warning("Failed to extract messages from checkpointer: %s", e)

    if last_run_stats:
        stats = {
            "token_usage": (last_run_stats.token_usage.to_dict() if last_run_stats.token_usage else {}),
            "duration_seconds": last_run_stats.duration_seconds,
            "status": (last_run_stats.status.value if last_run_stats.status else "unknown"),
        }
        progress = 1.0 if last_run_stats.status else 0.5

    return {
        "messages": messages,
        "context": context,
        "stats": stats,
        "progress": progress,
        "last_tool": last_tool,
    }
