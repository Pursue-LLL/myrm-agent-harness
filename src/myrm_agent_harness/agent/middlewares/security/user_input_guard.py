"""Screening of the user's messages before a model call: dangerous intent, prompt injection, PII.

Messages the runtime appends behind the user's are not the user's input and are never screened. A message may be text
or a list of blocks (text next to an image); every text block goes through the same three layers, in order, and a
block verdict ends the screening.

The latest user message is screened in full. One user input drives several model calls (one per tool round). The
first call, the one with no model or tool message behind the user's yet, writes: audit entries, logs, the safety
caution, PII rewrites and blocks. Every call also classifies PII so the privacy tracker follows the message, which a
WARN policy leaves unrewritten.

Earlier user messages reach the model again on every turn, so the policy applies to them too, silently: the PII
rewrite, and a block where the injection or dangerous-intent policy is fail_closed. They add no audit entries, logs
or safety caution, and the tracker rises to their level once. A policy that acts on none of them skips them. The
rewrites are stable under repetition, so rescanning the state on every call changes nothing after the first.

[INPUT]
- agent.middlewares._message_origin::is_user_authored_human_message (POS: Message-provenance predicate shared by the approval and security middlewares.)
- agent.middlewares._session_context::get_security_config (POS: Middleware session context — shared ContextVars for the middleware chain.)
- agent.middlewares.security.text_blocks::MessageContent, map_text_blocks (POS: Content-shape adapter between a message and the security layers that rewrite its text.)
- agent.middlewares.security.pii_actions::apply_pii_actions, blocking_level, levels_to_process (POS: PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard.)
- agent.security.detection.intent_router::scan_dangerous_intent (POS: Intake-stage dangerous intent router for defense-in-depth before ReAct loops.)
- agent.security.detection.prompt_guard::scan_input, log_guard_result (POS: Input-side injection detector. 10 EN + 4 ZH injection categories (OWASP LLM01 full coverage) with anti-obfuscation (leet speak, invisible Unicode, whitespace), word-boundary precision and a two-tier (audit vs block) score for prompt injection defense.)
- agent.security.detection.pii_classifier::classify_content (POS: Input-side PII classification engine. Runs the built-in patterns (bilingual CN/EN, in pii_patterns) with short-circuit optimization for efficient content scanning.)
- agent.security.guards.privacy_tracker::get_privacy_tracker (POS: Per-turn privacy state tracker. ContextVar session-scoped, independently evaluates each turn for privacy-sensitive content.)
- agent.security.audit::record_decision (POS: Cross-cutting concern. Called from tool_interceptor_middleware and all security guard modules at every decision point.)

[OUTPUT]
- screen_user_input: the message list with the user's messages screened, or None when nothing changed

[POS]
Input-side layers (intent router, prompt guard, PII guard) of the security guardrail middleware.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.middlewares._message_origin import is_user_authored_human_message
from myrm_agent_harness.agent.middlewares._session_context import get_security_config
from myrm_agent_harness.agent.middlewares.security.pii_actions import (
    apply_pii_actions,
    blocking_level,
    levels_to_process,
)
from myrm_agent_harness.agent.middlewares.security.text_blocks import MessageContent, map_text_blocks
from myrm_agent_harness.agent.security.audit import DecisionKind, record_decision
from myrm_agent_harness.agent.security.detection.intent_router import scan_dangerous_intent
from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content
from myrm_agent_harness.agent.security.detection.prompt_guard import log_guard_result, scan_input
from myrm_agent_harness.agent.security.guards.privacy_tracker import get_privacy_tracker
from myrm_agent_harness.agent.security.types import PrivacyPolicy, SecurityConfig, SensitivityLevel

logger = logging.getLogger(__name__)

# How a message is screened: the latest one on the first or a later model call of its input, or an earlier one.
Stage = Literal["first_call", "later_call", "earlier"]


def screen_user_input(messages: Sequence[BaseMessage], policy: PrivacyPolicy) -> list[BaseMessage] | None:
    """Screen the user-authored messages; return the rewritten message list, or None if it needs no change."""
    index = _latest_user_index(messages)
    if index is None:
        return None
    config = _security_config()
    replaced = _screen_earlier(messages, index, policy, config)
    latest = _screened(messages[index], _Screen(policy, config, _latest_stage(messages, index)))
    if latest is not None:
        replaced[index] = latest
    if not replaced:
        return None

    result = list(messages)
    for position, message in replaced.items():
        result[position] = message
    return result


def _screen_earlier(
    messages: Sequence[BaseMessage], latest_index: int, policy: PrivacyPolicy, config: SecurityConfig | None
) -> dict[int, BaseMessage]:
    """Screen the user messages before the latest one; the replacements by position."""
    if not _acts_on_earlier(policy, config):
        return {}
    replaced: dict[int, BaseMessage] = {}
    for position in range(latest_index):
        message = messages[position]
        if is_user_authored_human_message(message):
            replacement = _screened(message, _Screen(policy, config, "earlier"))
            if replacement is not None:
                replaced[position] = replacement
    return replaced


def _acts_on_earlier(policy: PrivacyPolicy, config: SecurityConfig | None) -> bool:
    """Whether the policy has anything to enforce on an earlier user message: PII handling, or a fail_closed block."""
    if policy.enabled:
        return True
    return config is not None and "fail_closed" in (config.injection_policy, config.dangerous_intent_policy)


def _screened(message: BaseMessage, screen: _Screen) -> BaseMessage | None:
    """The message after *screen*, or None when it stays as it is."""
    content = map_text_blocks(message.content, screen)
    if screen.blocked is not None:
        return None if message.content == screen.blocked else HumanMessage(content=screen.blocked, id=message.id)
    if screen.caution is not None:
        content = _with_caution(content, screen.caution)
    return None if content == message.content else message.model_copy(update={"content": content})


def _latest_user_index(messages: Sequence[BaseMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if is_user_authored_human_message(messages[index]):
            return index
    return None


def _latest_stage(messages: Sequence[BaseMessage], index: int) -> Stage:
    answered = any(isinstance(m, (AIMessage, ToolMessage)) for m in messages[index + 1 :])
    return "later_call" if answered else "first_call"


def _with_caution(content: MessageContent, caution: str) -> MessageContent:
    """Put the caution in front of the user's text. A message that already starts with it stays as it is."""
    if isinstance(content, str):
        return content if content.startswith(caution) else f"{caution}{content}"
    lead: dict[str, object] = {"type": "text", "text": caution}
    return content if content[:1] == [lead] else [lead, *content]


def _security_config() -> SecurityConfig | None:
    try:
        return get_security_config()
    except LookupError:
        return None


class _Screen:
    """Screens the text blocks of one user message. Keeps the block reply and the safety caution it produced."""

    __slots__ = ("audit", "blocked", "caution", "config", "earlier", "enforces", "policy")

    def __init__(self, policy: PrivacyPolicy, config: SecurityConfig | None, stage: Stage) -> None:
        self.policy = policy
        self.config = config
        self.audit = stage == "first_call"  # audit entries, logs and the safety caution
        self.enforces = stage != "later_call"  # intent and injection verdicts, PII rewrites and blocks
        self.earlier = stage == "earlier"
        self.blocked: str | None = None
        self.caution: str | None = None

    def __call__(self, text: str) -> str:
        if self.blocked is not None or not text:
            return text
        if self.enforces:
            self.blocked = self._intent(text) or self._injection(text)
            if self.blocked is not None:
                return text
        return self._pii(text)

    def _record(self, decision: DecisionKind, detail: str) -> None:
        if self.audit:
            record_decision("user_input", decision, detail)

    def _intent(self, text: str) -> str | None:
        mode = self.config.dangerous_intent_policy if self.config else "hitl"
        if self.earlier and mode != "fail_closed":
            return None
        result = scan_dangerous_intent(text)
        if result.safe:
            return None
        name = result.intent.value if result.intent else "unknown"
        detail = f"intent={name} pattern={result.matched_pattern}"
        self._record("DANGEROUS_INTENT_DETECTED", detail)
        if mode == "fail_closed":
            self._record("DANGEROUS_INTENT_BLOCKED", detail)
            if self.audit:
                logger.warning(
                    "[IntentRouter] Blocked dangerous intent user message: intent=%s pattern=%s",
                    name,
                    result.matched_pattern,
                )
            return (
                f"[BLOCKED_INTENT] This request was blocked by the safety router because "
                f"it contains a dangerous actionable operation intent ({name}). "
                f"Please confirm your request through the appropriate authorization channel or rephrase."
            )
        if mode == "hitl" and self.caution is None:
            self.caution = (
                f"[SAFETY_CAUTION: Actionable high-risk intent detected ({name}) - "
                f"do NOT execute destructive changes silently; require explicit confirmation]\n"
            )
        return None

    def _injection(self, text: str) -> str | None:
        mode = self.config.injection_policy if self.config else "log_only"
        if self.earlier and mode != "fail_closed":
            return None
        result = scan_input(text)
        if result.safe:
            return None
        if self.audit:
            log_guard_result(result, text)
        detail = f"patterns={','.join(result.patterns)} score={result.max_score:.2f}"
        self._record("INJECTION_DETECTED", detail)
        if mode == "fail_closed" and result.should_block:
            self._record("INJECTION_BLOCKED", detail)
            if self.audit:
                logger.warning(
                    "[INJECTION] Blocked user message: patterns=%s score=%.2f",
                    ",".join(result.patterns),
                    result.max_score,
                )
            return (
                "[BLOCKED] This message was blocked by the prompt injection guard. "
                "Please inform the user that their message triggered a security filter "
                "and was not processed. Do not attempt to guess or reproduce "
                "the original content."
            )
        return None

    def _pii(self, text: str) -> str:
        policy = self.policy
        if not policy.enabled:
            return text
        result = classify_content(text, policy)
        if result.level == SensitivityLevel.S1:
            return text
        tracker = get_privacy_tracker()
        if self.earlier:
            tracker.escalate(result.level, "user_history", result.patterns)
        else:
            tracker.record(result.level, "user_message", result.patterns)
        if not self.enforces:
            return text
        self._record("PII_DETECTED", f"level={result.level.value} patterns={','.join(result.patterns)}")
        levels = levels_to_process(text, result.level, policy)
        processed = apply_pii_actions(text, levels, policy, "user_input", audit=self.audit)
        if processed is None:
            blocking = blocking_level(policy, levels) or result.level
            self._record("PII_BLOCKED", f"level={blocking.value}")
            if self.audit:
                logger.warning("[PII] Blocked user message: level=%s", blocking.value)
            self.blocked = (
                "[BLOCKED] This message was blocked by the PII protection engine "
                f"due to {blocking.value}-level sensitive information. "
                "Please inform the user that their message contained confidential "
                "data and was not processed. Do not attempt to guess or reproduce "
                "the original content."
            )
        return processed if processed is not None else text
