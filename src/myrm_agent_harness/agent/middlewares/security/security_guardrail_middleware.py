"""Security guardrail middleware.

Eight-layer defense integrated as a LangChain AgentMiddleware:

awrap_model_call (wraps each LLM call, non-persistent request.override):
    0. Circuit Breaker Cognition — injects a transient HumanMessage via
       request.override when terminal errors are active (e.g. network_blocked,
       sandbox_ro, config_or_auth:search, config_or_auth:browser), so the LLM
       avoids planning doomed tool calls. Uses
       request.override so it never pollutes graph state or accumulates.
       Uses HumanMessage to preserve SystemMessage hash stability (prompt cache).
    Also marks the model call as covered by this middleware when a privacy policy is enabled, so the wire-level
       outbound privacy guard leaves the call alone.

before_model (runs before each LLM call):
    0.5 Intent Router — flags dangerous actionable operations in the user's message (block, or a safety caution)
    1. Prompt Guard — scans user input for 7 categories of injection attacks
    2. PII Guard — classifies user input into S1/S2/S3, applies redaction
       per PrivacyPolicy (warn/redact/block)
       Layers 0.5-2 screen the user-authored messages, text or text blocks (user_input_guard): the latest one in
       full, once per user input; earlier ones silently, because they reach the model again on every turn.
       Messages the runtime appends behind the user's are not screened.
    3. Tool Result Redact — sanitizes credentials in tool outputs, including the
       text blocks of a text + image result, so the LLM never sees raw secrets

after_model (runs after each LLM call):
    3.5 Canary Guard — checks if the session canary token leaked into AI
        output or tool call arguments. Deterministic detection of prompt
        injection success (zero false positives). Scrubs leaked token from
        output and records CANARY_LEAKED security decision.
    4. Leak Detector — scans AI response for 30+ credential patterns
    5. PII Redact — redacts PII from AI response when privacy is enabled
    6. History Redact — replaces detected credentials in the AI message stored
       in state, keeping conversation history clean for compliance and
       preventing credential accumulation across turns

A rewrite replaces only the message ``content`` (``model_copy``); status, metadata and ids stay intact.

Streaming note: ``before_model``/``after_model`` operate on the graph state,
not on streamed chunks. Streaming chunks are yielded during the model node
execution and are unaffected by these hooks. The primary value of layer ②③
is that the LLM never receives raw credentials/PII, so it cannot echo them.

[INPUT]
- agent.middlewares._session_context::get_canary_token, get_privacy_policy, get_terminal_errors (POS: Middleware session context — shared ContextVars for the middleware chain.)
- agent.security.detection.leak_detector::scan_for_leaks, redact_leaks, log_leaks (POS: Output-side credential leak detector. 40+ credential pattern matchers (API key prefixes + blockchain + cloud infra + ENV/JSON/Header context + Shannon entropy + PEM block-level multiline redaction) for preventing secret exfiltration.)
- agent.security.detection.canary_guard::check_canary, scrub_canary (POS: Output-side injection detector. Deterministic canary token for prompt injection success detection.)
- agent.security.audit::record_decision (POS: Cross-cutting concern. Called from tool_interceptor_middleware and all security guard modules at every decision point.)
- agent.middlewares.security.user_input_guard::screen_user_input (POS: Input-side layers (intent router, prompt guard, PII guard) of the security guardrail middleware.)
- agent.middlewares.security.pii_actions::apply_privacy_policy (POS: PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard.)
- agent.middlewares.security.outbound_privacy_guard::privacy_enforced_by_loop (POS: Wire-level privacy guard for the model calls this middleware does not cover.)
- agent.middlewares.security.text_blocks::map_text_blocks (POS: Content-shape adapter between a message and the security layers that rewrite its text.)

[OUTPUT]
- SecurityGuardrailMiddleware: Eight-layer security guardrail for agent conversations.

[POS]
Security guardrail middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import cast

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langgraph.runtime import Runtime

from myrm_agent_harness.agent.middlewares._session_context import (
    get_canary_token,
    get_privacy_policy,
    get_terminal_errors,
)
from myrm_agent_harness.agent.middlewares.security.outbound_privacy_guard import privacy_enforced_by_loop
from myrm_agent_harness.agent.middlewares.security.pii_actions import apply_privacy_policy
from myrm_agent_harness.agent.middlewares.security.text_blocks import map_text_blocks
from myrm_agent_harness.agent.middlewares.security.user_input_guard import screen_user_input
from myrm_agent_harness.agent.security.detection.leak_detector import (
    log_leaks,
    redact_leaks,
    scan_for_leaks,
)

logger = logging.getLogger(__name__)


_CIRCUIT_BREAKER_HINTS: dict[str, str] = {
    "network_blocked": (
        "Network access is BLOCKED in this environment. "
        "Do NOT call any network/web/browser/fetch/search tools. "
        "Use local data, generate mock data, or ask the user to provide it."
    ),
    "sandbox_ro": (
        "The filesystem is READ-ONLY in this environment. "
        "Do NOT call file_write/file_edit/mkdir or any write tools outside /workspace. "
        "All output MUST be written to /workspace."
    ),
    "config_or_auth:search": (
        "Search tools are currently unavailable because the search service "
        "configuration or credentials are invalid. Do NOT retry search tools. "
        "Use browser tools or web_fetch tools to gather information instead."
    ),
    "config_or_auth:browser": (
        "Browser tools are currently unavailable because the browser "
        "environment cannot be launched. Do NOT retry browser tools. "
        "Use search tools or web_fetch tools to gather information instead."
    ),
}


def _last_ai_message(messages: Sequence[BaseMessage]) -> tuple[int, AIMessage] | None:
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage):
            return i, msg
    return None


def _redact_recent_tool_results(messages: Sequence[BaseMessage]) -> list[BaseMessage] | None:
    """Layer ③: redact credentials in the tool results since the last AI or human message.

    Returns the rewritten list, or None when no result held a credential.
    """
    redacted: list[BaseMessage] | None = None
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, ToolMessage):
            content = map_text_blocks(msg.content, redact_leaks)
            if content != msg.content:
                if redacted is None:
                    redacted = list(messages)
                redacted[i] = msg.model_copy(update={"content": content})
                logger.warning("[SECURITY] Redacted credentials in tool result: %s", msg.name or "unknown")
        elif isinstance(msg, (AIMessage, HumanMessage)):
            break
    return redacted


def _guard_canary(text: str, tool_calls: list[ToolCall]) -> str:
    """Layer ③.5: record a session canary token that leaked into the AI text or its tool call arguments.

    Returns *text* with the token scrubbed. The arguments are checked on their own: a model that writes no text next
    to a tool call can still carry the token out through it.
    """
    canary = get_canary_token()
    if not canary:
        return text

    from myrm_agent_harness.agent.security.detection.canary_guard import (
        StructuredValue,
        check_canary,
        scrub_canary,
    )

    text_leaked = check_canary(text, canary)
    # ToolCall is a TypedDict of JSON values, which the recursive StructuredValue alias cannot express.
    args_leaked = bool(tool_calls) and check_canary(cast("StructuredValue", tool_calls), canary)
    if not (text_leaked or args_leaked):
        return text

    from myrm_agent_harness.agent.security.audit import record_decision

    channel = "text+tool_args" if text_leaked and args_leaked else "text" if text_leaked else "tool_args"
    record_decision("canary_guard", "CANARY_LEAKED", f"channel={channel}", tainted=True)
    logger.warning("[CANARY] Prompt injection detected: canary leaked via %s", channel)
    return scrub_canary(text, canary)


def _redact_ai_text(text: str) -> str:
    """Layers ④⑤: redact credentials, then apply the privacy policy to PII in the AI text."""
    matches = scan_for_leaks(text)
    if matches:
        log_leaks(matches, text)
        text = redact_leaks(text)
    # BLOCK in after_model: an already-generated response can't be blocked, so it is fully redacted instead.
    return apply_privacy_policy(text, get_privacy_policy(), "ai_response")


class SecurityGuardrailMiddleware(AgentMiddleware):
    """Eight-layer security guardrail for agent conversations."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Layer 0: Circuit Breaker Cognition via transient request.override.

        Injects a HumanMessage with environment constraints when terminal errors
        are active. Uses request.override so it never persists into graph state.
        """
        terminal_errors = get_terminal_errors().get_all()
        if terminal_errors:
            constraints: list[str] = []
            # A global network block supersedes family-scoped config/auth
            # guidance — injecting both would contradict each other
            # ("don't call browser" + "use browser tools").
            network_blocked = "network_blocked" in terminal_errors
            for err in sorted(terminal_errors):
                if network_blocked and err.startswith("config_or_auth:"):
                    continue
                if err in _CIRCUIT_BREAKER_HINTS:
                    constraints.append(_CIRCUIT_BREAKER_HINTS[err])
                else:
                    constraints.append(
                        f"Capability '{err}' is UNAVAILABLE in this environment. "
                        f"Do NOT call tools that depend on '{err}'."
                    )
            if constraints:
                constraint_text = "[SYSTEM_ENFORCED] Environment capability constraints detected:\n" + "\n".join(
                    f"- {c}" for c in constraints
                )
                new_messages = [*list(request.messages), HumanMessage(content=constraint_text)]
                logger.info("Circuit breaker cognition injected: %s", sorted(terminal_errors))
                request = request.override(messages=new_messages)
        # The model call below carries messages this middleware already screened under the policy; the wire-level
        # guard must not process them a second time.
        with privacy_enforced_by_loop(get_privacy_policy().enabled):
            return await handler(request)

    def before_model(self, state: AgentState, runtime: Runtime) -> dict[str, Sequence[BaseMessage]] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        screened = screen_user_input(messages, get_privacy_policy())
        redacted = _redact_recent_tool_results(messages if screened is None else screened)
        result = screened if redacted is None else redacted
        return None if result is None else {"messages": result}

    def after_model(self, state: AgentState, runtime: Runtime) -> dict[str, Sequence[BaseMessage]] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai = _last_ai_message(messages)
        if last_ai is None:
            return None
        last_ai_idx, last_ai_msg = last_ai

        content = last_ai_msg.content
        modified = _guard_canary(content if isinstance(content, str) else "", last_ai_msg.tool_calls)
        if modified:
            modified = _redact_ai_text(modified)

        # Layer ⑥: History Redact — replace in stored message
        if not isinstance(content, str) or modified == content:
            return None

        new_messages = list(messages)
        new_messages[last_ai_idx] = last_ai_msg.model_copy(update={"content": modified})

        return {"messages": new_messages}
