"""Security guardrail middleware.

Eight-layer defense integrated as a LangChain AgentMiddleware:

awrap_model_call (wraps each LLM call, non-persistent request.override):
    0. Circuit Breaker Cognition — injects a transient HumanMessage via
       request.override when terminal errors are active (e.g. network_blocked,
       sandbox_ro), so the LLM avoids planning doomed tool calls. Uses
       request.override so it never pollutes graph state or accumulates.
       Uses HumanMessage to preserve SystemMessage hash stability (prompt cache).

before_model (runs before each LLM call):
    1. Prompt Guard — scans user input for 7 categories of injection attacks
    2. PII Guard — classifies user input into S1/S2/S3, applies redaction
       per PrivacyPolicy (warn/redact/block)
    3. Tool Result Redact — sanitizes credentials in tool outputs so the LLM
       never sees raw secrets (source-level prevention)

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

Streaming note: ``before_model``/``after_model`` operate on the graph state,
not on streamed chunks. Streaming chunks are yielded during the model node
execution and are unaffected by these hooks. The primary value of layer ②③
is that the LLM never receives raw credentials/PII, so it cannot echo them.

[INPUT]
- agent.security.types::PIIAction, SensitivityLevel (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)

[OUTPUT]
- SecurityGuardrailMiddleware: Eight-layer security guardrail for agent conversations.

[POS]
Security guardrail middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares._session_context import (
    get_canary_token,
    get_privacy_policy,
    get_pseudonym_store,
    get_terminal_errors,
)
from myrm_agent_harness.agent.security.detection.leak_detector import (
    log_leaks,
    redact_leaks,
    scan_for_leaks,
)
from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content
from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
from myrm_agent_harness.agent.security.detection.prompt_guard import (
    log_guard_result,
    scan_input,
)
from myrm_agent_harness.agent.security.guards.privacy_tracker import get_privacy_tracker
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel

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
}


def _levels_to_process(
    detected_level: SensitivityLevel,
    policy: PrivacyPolicy,
) -> list[SensitivityLevel]:
    """Determine which sensitivity levels need PII processing.

    When S3 is detected, also include S2 if its action is not WARN
    (since the message may contain both S2 and S3 PII).
    """
    levels = [detected_level]
    if detected_level == SensitivityLevel.S3 and policy.s2_action != PIIAction.WARN:
        levels.append(SensitivityLevel.S2)
    return levels


def _apply_pii_actions(
    text: str,
    levels: list[SensitivityLevel],
    policy: PrivacyPolicy,
    source: str,
) -> str | None:
    """Apply per-level PII actions to *text*.

    Returns None if the message should be BLOCKED, otherwise returns
    the processed text (possibly unchanged if only WARN actions).
    """
    from myrm_agent_harness.agent.security.audit import record_decision

    result = text
    for level in levels:
        action = policy.s3_action if level == SensitivityLevel.S3 else policy.s2_action
        if action == PIIAction.BLOCK:
            return None
        if action == PIIAction.PSEUDONYMIZE:
            store = get_pseudonym_store()
            if store is not None:
                from myrm_agent_harness.agent.security.detection.pseudonymizer import (
                    pseudonymize_text,
                )

                ps_result = pseudonymize_text(result, store, level)
                if ps_result.count > 0:
                    result = ps_result.text
                    record_decision(source, "PII_PSEUDONYMIZED", f"level={level.value} count={ps_result.count}")
                    logger.warning("[PII] Pseudonymized %d %s items (%s)", ps_result.count, level.value, source)
            else:
                result, count = redact_pii(result)
                if count > 0:
                    record_decision(
                        source, "PII_REDACTED", f"level={level.value} count={count} (pseudonymize fallback)"
                    )
                    logger.warning("[PII] Pseudonymize fallback to redact: %d items (%s)", count, source)
        elif action == PIIAction.REDACT:
            result, count = redact_pii(result)
            if count > 0:
                record_decision(source, "PII_REDACTED", f"level={level.value} count={count}")
                logger.warning("[PII] Redacted %d %s items (%s)", count, level.value, source)
    return result


class SecurityGuardrailMiddleware(AgentMiddleware):  # type: ignore[type-arg]
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
            for err in sorted(terminal_errors):
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
                return await handler(request.override(messages=new_messages))
        return await handler(request)

    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        new_messages: list[Any] | None = None

        policy = get_privacy_policy()

        # Layer ①: Prompt Guard — scan last HumanMessage for injection
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                if isinstance(content, str):
                    result = scan_input(content)
                    if not result.safe:
                        log_guard_result(result, content)
                    # Layer ②: PII Guard — classify and apply per-level actions
                    if policy.enabled:
                        pii_result = classify_content(content, policy)
                        if pii_result.level != SensitivityLevel.S1:
                            tracker = get_privacy_tracker()
                            tracker.record(pii_result.level, "user_message", pii_result.patterns)
                            from myrm_agent_harness.agent.security.audit import (
                                record_decision,
                            )

                            record_decision(
                                "user_input",
                                "PII_DETECTED",
                                f"level={pii_result.level.value} patterns={','.join(pii_result.patterns)}",
                            )
                            levels_to_process = _levels_to_process(pii_result.level, policy)
                            processed = _apply_pii_actions(
                                content,
                                levels_to_process,
                                policy,
                                "user_input",
                            )
                            if processed is None:
                                if new_messages is None:
                                    new_messages = list(messages)
                                idx = messages.index(msg)
                                new_messages[idx] = HumanMessage(
                                    content=(
                                        "[BLOCKED] This message was blocked by the PII protection engine "
                                        f"due to {pii_result.level.value}-level sensitive information. "
                                        "Please inform the user that their message contained confidential "
                                        "data and was not processed. Do not attempt to guess or reproduce "
                                        "the original content."
                                    ),
                                    id=msg.id,
                                )
                                record_decision(
                                    "user_input",
                                    "PII_BLOCKED",
                                    f"level={pii_result.level.value}",
                                )
                                logger.warning(
                                    "[PII] Blocked user message: level=%s",
                                    pii_result.level.value,
                                )
                            elif processed != content:
                                if new_messages is None:
                                    new_messages = list(messages)
                                idx = messages.index(msg)
                                new_messages[idx] = HumanMessage(content=processed, id=msg.id)
                break

        # Layer ③: Tool Result Redact — sanitize credentials in recent ToolMessages
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, ToolMessage) and isinstance(msg.content, str):
                redacted = redact_leaks(msg.content)
                if redacted != msg.content:
                    if new_messages is None:
                        new_messages = list(messages)
                    new_messages[i] = ToolMessage(
                        content=redacted,
                        tool_call_id=msg.tool_call_id,
                        name=msg.name,
                        id=msg.id,
                    )
                    logger.warning(
                        "[SECURITY] Redacted credentials in tool result: %s",
                        msg.name or "unknown",
                    )
            elif isinstance(msg, (AIMessage, HumanMessage)):
                break

        if new_messages is not None:
            return {"messages": new_messages}
        return None

    def after_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai_idx: int | None = None
        last_ai_msg: AIMessage | None = None
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], AIMessage):
                last_ai_idx = i
                last_ai_msg = messages[i]
                break

        if last_ai_idx is None or last_ai_msg is None:
            return None

        content = last_ai_msg.content
        if not isinstance(content, str) or not content:
            return None

        modified = content

        # Layer ③.5: Canary Guard — deterministic injection success detection
        canary = get_canary_token()
        if canary:
            from myrm_agent_harness.agent.security.detection.canary_guard import (
                check_canary,
                scrub_canary,
            )

            text_leaked = check_canary(modified, canary)
            args_leaked = bool(last_ai_msg.tool_calls) and check_canary(last_ai_msg.tool_calls, canary)
            if text_leaked or args_leaked:
                from myrm_agent_harness.agent.security.audit import record_decision

                channel = "text" if text_leaked else "tool_args"
                if text_leaked and args_leaked:
                    channel = "text+tool_args"
                record_decision(
                    "canary_guard",
                    "CANARY_LEAKED",
                    f"channel={channel}",
                    tainted=True,
                )
                logger.warning(
                    "[CANARY] Prompt injection detected: canary leaked via %s",
                    channel,
                )
                modified = scrub_canary(modified, canary)

        # Layer ④: Leak Detector — scan for credential patterns
        matches = scan_for_leaks(modified)
        if matches:
            log_leaks(matches, modified)
            modified = redact_leaks(modified)

        # Layer ⑤: PII Redact — redact PII from AI response
        policy = get_privacy_policy()
        if policy.enabled:
            pii_result = classify_content(modified, policy)
            if pii_result.level != SensitivityLevel.S1:
                levels_to_process = _levels_to_process(pii_result.level, policy)
                result = _apply_pii_actions(
                    modified,
                    levels_to_process,
                    policy,
                    "ai_response",
                )
                if result is None:
                    # BLOCK in after_model: can't block an already-generated
                    # response, fallback to full redaction
                    modified, _ = redact_pii(modified)
                else:
                    modified = result

        # Layer ⑥: History Redact — replace in stored message
        if modified == content:
            return None

        updated = AIMessage(
            content=modified,
            id=last_ai_msg.id,
            name=last_ai_msg.name,
            tool_calls=last_ai_msg.tool_calls,
        )
        new_messages = list(messages)
        new_messages[last_ai_idx] = updated

        return {"messages": new_messages}
