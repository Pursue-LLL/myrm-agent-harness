"""Tool approval middleware — intercepts tool calls that require user confirmation.

Uses ``after_model`` hook to intercept AIMessage with tool_calls *before* execution.
Decision flow:

1. evaluate_tool_call() → ALLOW / ASK / DENY
2. ALLOW: taint check → proceed or escalate to ASK
3. DENY: inject artificial ToolMessage with error
4. ASK: domain HITL runtime check → cron pre-approval → allowlist → batch interrupt()

Batch approval: When multiple tools require approval in a single turn, all are
collected and presented in one interrupt() call. Users decide for all tools at once.

Domain HITL: When ``domain_hitl_enabled`` is True, URL-bearing tools (web_fetch,
browser_navigate) whose hostname is not in ``network_allowlist`` trigger ASK.
Users can approve per-request or "always allow this domain" (session-scoped).

Cron sessions (session_key starts with "cron:") promote ASK to ALLOW
because the Capability Fence declaration acts as pre-approval. Undeclared
capabilities are rejected at the Capability Fence layer before reaching ASK.

Uses LangGraph's native ``interrupt()`` mechanism for Human-in-the-Loop:
- First call: interrupt() raises GraphInterrupt, stream ends
- Resume: interrupt() returns resume_value (user decisions list), execution continues

Every decision is recorded via security.audit.record_decision() for post-hoc auditing.

[INPUT]
- middlewares._session_context::get_security_config, (POS: Middleware session context — shared ContextVars for the middleware chain.)
- agent.security.tool_registry::compute_canonical_args_hash (POS: Pure functions, no side effects, trivially testable. Browser tools use dynamic resolution: browser_interact's permission varies by ``action`` parameter (fill→browser_fill, upload_file→browser_upload, etc.). MCP tools (``mcp__`` prefixed) and unknown tools both map to ``mcp_invoke``. Canonical parameter hashing ensures same functional operation produces same hash, regardless of LLM's wording variations in auxiliary fields. Safety metadata declares all built-in tools with four categories: read-only concurrent-safe, concurrent-safe with side effects, destructive, and stateful. Undeclared tools (e.g. MCP) get fail-closed defaults. Used by safety_dispatcher middleware for concurrency control.)
- langgraph.types::interrupt (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- ToolApprovalMiddleware: after_model middleware orchestrating batch approval flow

[POS]
Bridges the Permission Engine with the LangGraph tool pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import interrupt

from myrm_agent_harness.agent.middlewares._session_context import (
    get_approval_session,
    get_is_shadow_agent,
    get_is_subagent,
    get_security_config,
    get_workspace_root,
    set_security_config,
)
from myrm_agent_harness.agent.security.tool_registry import compute_canonical_args_hash
from myrm_agent_harness.agent.security.types import RecentToolCall

from .batch_processor import apply_approval_decisions, build_interrupt_payload, evaluate_tool_batch
from .helpers import reset_denial_counter

logger = logging.getLogger(__name__)


class ToolApprovalMiddleware(AgentMiddleware[Any, Any, Any]):
    """Tool approval middleware using after_model hook for batch approval."""

    async def aafter_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        """Intercept AIMessage with tool_calls before execution.

        Orchestrates batch approval flow: evaluate → interrupt → apply decisions.
        """
        config = get_security_config()
        if config is None:
            from myrm_agent_harness.agent.security.channel_presets import (
                build_channel_security_config,
            )

            logger.error(
                "[SECURITY] security_config missing in async context — "
                "applying fail-closed web_chat defaults (session=%s)",
                get_approval_session(),
            )
            config = build_channel_security_config("web_chat", None, local_mode=True)
            set_security_config(config)

        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai_msg = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        session_key = get_approval_session()
        workspace_root = get_workspace_root() or None
        is_cron = session_key.startswith("cron:")

        args_hashes = {
            idx: compute_canonical_args_hash(tc.get("name", "unknown"), tc.get("args"))
            for idx, tc in enumerate(last_ai_msg.tool_calls)
        }

        # Extract recent human messages for intent context (Reasoning-Blind: only user text)
        from langchain_core.messages import HumanMessage

        recent_human_msgs = [
            msg.content for msg in messages[-10:] if isinstance(msg, HumanMessage) and isinstance(msg.content, str)
        ]
        intent_context = "\n".join(recent_human_msgs) if recent_human_msgs else None

        if intent_context and len(intent_context) > 2000:
            intent_context = intent_context[:2000] + "\n... (truncated for length)"

        # Extract recent tool call sequence for cross-tool context (Reasoning-Blind)
        window_size = config.transcript_window_size
        recent_tool_calls: tuple[RecentToolCall, ...] = ()
        if config.auto_mode_enabled:
            tc_list: list[RecentToolCall] = []
            for msg in messages[-(window_size * 2) :]:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tc_list.append(
                            RecentToolCall(
                                tool_name=tc.get("name", "unknown"),
                                args=tc.get("args", {}),
                            )
                        )
            recent_tool_calls = tuple(tc_list[-window_size:])

        # Extract session-level taint labels for the classifier
        session_taint_labels: frozenset[str] | None = None
        if config.auto_mode_enabled:
            from myrm_agent_harness.agent.security.guards.taint_tracker import (
                get_taint_tracker,
            )

            tracker = get_taint_tracker()
            if tracker.is_tainted:
                session_taint_labels = frozenset(str(lbl) for lbl in tracker.labels)

        _auto_approved, auto_denied, pending_approval = await evaluate_tool_batch(
            last_ai_msg.tool_calls,
            config,
            is_cron,
            workspace_root,
            session_key,
            args_hashes,
            intent_context=intent_context,
            recent_tool_calls=recent_tool_calls,
            taint_labels=session_taint_labels,
        )

        if pending_approval:
            from myrm_agent_harness.agent.middlewares._session_context import get_approval_user_id
            from myrm_agent_harness.agent.middlewares.approval import get_approval_rate_limiter
            from myrm_agent_harness.agent.security.audit import record_decision

            user_id = get_approval_user_id()
            if user_id:
                rate_limiter = get_approval_rate_limiter()
                if not rate_limiter.check_limit(user_id):
                    logger.warning("[RATE_LIMIT] Approval rate limit exceeded for user %s", user_id)
                    for idx, tool_call, _permission_type, _reason, _ in pending_approval:
                        auto_denied.append(
                            (
                                idx,
                                tool_call,
                                " Too many approval requests. Rate limit exceeded. Please try again later.",
                            )
                        )
                        record_decision(tool_call.get("name", "unknown"), "DENY", "Approval rate limit exceeded")
                    pending_approval.clear()

        if not pending_approval:
            if auto_denied:
                revised_tool_calls = []
                artificial_tool_messages = []

                for idx, tool_call in enumerate(last_ai_msg.tool_calls):
                    denied = next(((d_idx, tc, msg) for d_idx, tc, msg in auto_denied if d_idx == idx), None)
                    if denied:
                        _, _, error_msg = denied
                        artificial_tool_messages.append(
                            ToolMessage(
                                content=error_msg,
                                name=tool_call.get("name", "unknown"),
                                tool_call_id=tool_call.get("id", ""),
                                status="error",
                            )
                        )
                    else:
                        revised_tool_calls.append(tool_call)

                last_ai_msg.tool_calls = revised_tool_calls
                return {"messages": [last_ai_msg, *artificial_tool_messages]}
            return None

        # We use LangGraph's native interrupt() mechanism for ALL agents, including subagents.
        # Subagents must have a checkpointer configured for this to work.
        # The executor catches the GraphInterrupt and delegates it to the parent agent.

        payload, interrupt_indices = build_interrupt_payload(
            pending_approval,
            session_key,
            approval_timeout_seconds=config.approval_timeout_seconds,
            timeout_behavior=config.approval_timeout_behavior,
            workspace_root=workspace_root,
        )

        # Determine the action type based on agent context
        action_type = "subagent_approval" if get_is_subagent() else "tool_approval"

        # Inject action_type and subagent_task_id into payload so the UI knows how to render it
        # and the server knows how to route the approval resolution.
        if get_is_subagent():
            from myrm_agent_harness.agent.middlewares._session_context import get_subagent_task_id

            task_id = get_subagent_task_id()
            if not task_id:
                logger.warning("Subagent context active but no task_id found. Falling back to auto-deny.")
                return self._fallback_auto_deny(last_ai_msg, pending_approval, auto_denied, session_key)
            payload["action_type"] = action_type
            payload["subagent_task_id"] = task_id

        # Shadow agents have no UI channel — auto-deny to prevent deadlocks.
        if get_is_shadow_agent():
            logger.warning(
                "[SHADOW_AGENT_APPROVAL_BLOCKED] Shadow agent attempted high-risk operation "
                "requiring user approval — auto-denying. session_key=%s",
                session_key,
            )
            return self._fallback_auto_deny(last_ai_msg, pending_approval, auto_denied, session_key)

        batch_response = interrupt(payload)

        if not isinstance(batch_response, dict):
            logger.error("[BATCH_APPROVAL] Invalid batch response type: %s", type(batch_response))
            decisions = [{"type": "reject", "feedback": "Invalid batch response"} for _ in pending_approval]
        else:
            if "decision" in batch_response and "decisions" not in batch_response:
                # Global decision from text interception
                global_decision = batch_response["decision"]
                global_feedback = batch_response.get("feedback")
                decisions = [{"type": global_decision, "feedback": global_feedback} for _ in pending_approval]
            else:
                decisions = batch_response.get("decisions", [])

            if len(decisions) != len(pending_approval):
                logger.error(
                    "[BATCH_APPROVAL] Decision count mismatch: expected %d, got %d",
                    len(pending_approval),
                    len(decisions),
                )
                decisions = [{"type": "reject", "feedback": "Decision count mismatch"} for _ in pending_approval]

        logger.info("[BATCH_APPROVAL] Batch interrupt resolved with %d decisions", len(decisions))

        revised_tool_calls, artificial_tool_messages, guidance_messages = await apply_approval_decisions(
            decisions,
            last_ai_msg,
            auto_denied,
            pending_approval,
            interrupt_indices,
            args_hashes,
            config=config,
        )

        # Fire APPROVAL_CORRECTION hook for edit/reject decisions so memory system can learn
        await self._fire_correction_hook(decisions, pending_approval, session_key)

        last_ai_msg.tool_calls = revised_tool_calls
        result_messages: list = [last_ai_msg, *artificial_tool_messages]
        if guidance_messages:
            result_messages.extend(guidance_messages)
        return {"messages": result_messages}

    @staticmethod
    async def _fire_correction_hook(
        decisions: list[dict[str, Any]],
        pending_approval: list,
        session_key: str,
    ) -> None:
        """Fire APPROVAL_CORRECTION hook for edit/reject decisions.

        Also emits a CORRECTION_LEARNED SSE event so the frontend can show feedback.
        """
        corrections: list[dict[str, object]] = []

        for i, decision in enumerate(decisions):
            if i >= len(pending_approval):
                break
            decision_type = decision.get("type", "")
            if decision_type not in ("edit", "reject"):
                continue

            idx, tool_call, _perm_type, _reason, _ = pending_approval[i]
            tool_name = tool_call.get("name", "unknown")
            original_args = dict(tool_call.get("args", {})) if isinstance(tool_call.get("args"), dict) else {}

            correction: dict[str, object] = {
                "tool_name": tool_name,
                "decision_type": decision_type,
                "feedback": decision.get("feedback", ""),
            }

            if decision_type == "edit":
                edited_args = decision.get("args")
                correction["original_args"] = original_args
                correction["edited_args"] = dict(edited_args) if isinstance(edited_args, dict) else original_args
            else:
                correction["original_args"] = original_args
                correction["edited_args"] = None

            corrections.append(correction)

        if not corrections:
            return

        try:
            from myrm_agent_harness.agent.hooks import fire_hook
            from myrm_agent_harness.core.hooks.types import HookEvent

            result = await fire_hook(
                HookEvent.APPROVAL_CORRECTION,
                {"session_id": session_key, "corrections": tuple(corrections)},
            )

            # Emit SSE event with learning summaries for frontend toast
            summaries = [r.output for r in result.results if r.output] if result.results else []
            if summaries:
                try:
                    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                    await dispatch_custom_event(
                        "correction_learned",
                        {"summaries": summaries, "session_id": session_key},
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[APPROVAL] Failed to fire correction hook: %s", e)

    def _fallback_auto_deny(
        self, last_ai_msg: AIMessage, pending_approval: list, auto_denied: list, session_key: str
    ) -> dict[str, Any]:
        """Auto-deny tools when task_id is missing to prevent deadlock."""
        logger.warning(
            "[SUBAGENT_APPROVAL_BLOCKED] Autonomous subagent attempted high-risk operation "
            "requiring user approval — auto-denying to prevent deadlock. "
            f"session_key={session_key}, pending_tools={[tc.get('name') for _, tc, _, _, _ in pending_approval]}"
        )

        try:
            from myrm_agent_harness.observability.metrics.registry import get_metrics_registry

            metrics_registry = get_metrics_registry()
            if metrics_registry and metrics_registry.enabled:
                for _, tool_call, _, _, _ in pending_approval:
                    metrics_registry.record_approval_denied(
                        agent_id="base_agent",
                        tool_name=tool_call.get("name", "unknown"),
                        reason="subagent_auto_deny",
                    )
        except ImportError:
            pass

        revised_tool_calls = []
        artificial_tool_messages = []

        for idx, tool_call in enumerate(last_ai_msg.tool_calls):
            is_pending = any(p_idx == idx for p_idx, _, _, _, _ in pending_approval)

            if is_pending:
                error_msg = (
                    "[SYSTEM_ENFORCED] High-risk operations requiring user UI approval "
                    "are strictly forbidden for autonomous Subagents when task_id is missing. "
                    "This safeguard prevents deadlocks since Subagents have no frontend channel. "
                    "Please use a safe alternative or delegate this operation to the parent agent."
                )
                artificial_tool_messages.append(
                    ToolMessage(
                        content=error_msg,
                        name=tool_call.get("name", "unknown"),
                        tool_call_id=tool_call.get("id", ""),
                        status="error",
                    )
                )

                from myrm_agent_harness.agent.security.audit import record_decision

                record_decision(
                    tool_call.get("name", "unknown"),
                    "SUBAGENT_AUTO_DENY",
                    "Autonomous subagent blocked from triggering UI approval flow (missing task_id)",
                )
            else:
                revised_tool_calls.append(tool_call)

        for _d_idx, tool_call, error_msg in auto_denied:
            artificial_tool_messages.append(
                ToolMessage(
                    content=error_msg,
                    name=tool_call.get("name", "unknown"),
                    tool_call_id=tool_call.get("id", ""),
                    status="error",
                )
            )

        last_ai_msg.tool_calls = revised_tool_calls
        return {"messages": [last_ai_msg, *artificial_tool_messages]}


__all__ = [
    "ToolApprovalMiddleware",
    "reset_denial_counter",
]
