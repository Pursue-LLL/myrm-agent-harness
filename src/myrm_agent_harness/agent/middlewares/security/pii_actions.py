"""Per-level PII actions (warn, redact, pseudonymize, block) applied to a text under a PrivacyPolicy.

[INPUT]
- agent.security.types::PIIAction, PrivacyPolicy, SensitivityLevel (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)
- core.security.detection.custom_rules::custom_rules (POS: Single definition of custom-term matching for the privacy policy: the PII classifier, the redactor and the pseudonymizer share it, so detection and masking never disagree about what a user's keyword or pattern covers.)
- agent.security.detection.pii_classifier::classify_content, contains_level (POS: Input-side PII classification engine. Runs the built-in patterns (bilingual CN/EN, in pii_patterns) with short-circuit optimization for efficient content scanning.)

[OUTPUT]
- action_at: the action the policy sets for a level
- blocking_level: the first of the given levels whose action is block, the level that refuses a text
- levels_to_process: the sensitivity levels a text obliges the policy to act on: its detected level, plus S2 when an S3 text holds S2 content too and S2's action acts
- apply_pii_actions: apply the policy action of each level to a text, audited unless ``audit=False``; None when a level blocks
- apply_privacy_policy: classify a text and apply the policy to it; a block becomes full redaction, so the text always comes back

[POS]
PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard. The action of a level covers the built-in detectors and the user's custom keywords and patterns of that level, and only those: the redaction of one level never masks the content of another, and a level blocks only a text that holds it.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.middlewares._session_context import get_pseudonym_store
from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content, contains_level
from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel
from myrm_agent_harness.core.security.detection.custom_rules import custom_rules

logger = logging.getLogger(__name__)


def action_at(policy: PrivacyPolicy, level: SensitivityLevel) -> PIIAction:
    """The action the user chose for *level*: S3 has its own, every other level follows S2's."""
    return policy.s3_action if level == SensitivityLevel.S3 else policy.s2_action


def blocking_level(policy: PrivacyPolicy, levels: list[SensitivityLevel]) -> SensitivityLevel | None:
    """The first of *levels* whose action is BLOCK, the level that refuses the text; None when none does."""
    return next((level for level in levels if action_at(policy, level) == PIIAction.BLOCK), None)


def levels_to_process(
    content: str,
    detected_level: SensitivityLevel,
    policy: PrivacyPolicy,
) -> list[SensitivityLevel]:
    """The sensitivity levels *content* obliges the policy to act on.

    The detected level is always one. A text that reaches S3 may hold S2 content as well, so S2 joins it when the text
    does hold some and its action is not WARN: a level the text does not hold is not acted on, which matters for a
    BLOCK, where the message would be refused for content it does not contain.
    """
    levels = [detected_level]
    if (
        detected_level == SensitivityLevel.S3
        and policy.s2_action != PIIAction.WARN
        and contains_level(content, policy, SensitivityLevel.S2)
    ):
        levels.append(SensitivityLevel.S2)
    return levels


def apply_pii_actions(
    text: str,
    levels: list[SensitivityLevel],
    policy: PrivacyPolicy,
    source: str,
    *,
    audit: bool = True,
) -> str | None:
    """Apply per-level PII actions to *text*.

    Returns None if the message should be BLOCKED, otherwise returns
    the processed text (possibly unchanged if only WARN actions).

    Every rewrite is recorded in the audit log and logged. A caller that applies the policy to a text it already
    recorded once (a user message handed to the model again on a later turn) passes ``audit=False``: same rewrite,
    no second entry.
    """
    from myrm_agent_harness.agent.security.audit import DecisionKind, record_decision

    def report(decision: DecisionKind, detail: str, message: str, *args: object) -> None:
        if audit:
            record_decision(source, decision, detail)
            logger.warning(message, *args)

    result = text
    for level in levels:
        action = action_at(policy, level)
        if action == PIIAction.BLOCK:
            return None
        custom = custom_rules(policy, level)
        only = frozenset({level})
        if action == PIIAction.PSEUDONYMIZE:
            store = get_pseudonym_store()
            if store is not None:
                from myrm_agent_harness.agent.security.detection.pseudonymizer import (
                    pseudonymize_text,
                )

                ps_result = pseudonymize_text(result, store, level, custom)
                if ps_result.count > 0:
                    result = ps_result.text
                    report(
                        "PII_PSEUDONYMIZED",
                        f"level={level.value} count={ps_result.count}",
                        "[PII] Pseudonymized %d %s items (%s)",
                        ps_result.count,
                        level.value,
                        source,
                    )
            else:
                result, count = redact_pii(result, custom, only)
                if count > 0:
                    report(
                        "PII_REDACTED",
                        f"level={level.value} count={count} (pseudonymize fallback)",
                        "[PII] Pseudonymize fallback to redact: %d items (%s)",
                        count,
                        source,
                    )
        elif action == PIIAction.REDACT:
            result, count = redact_pii(result, custom, only)
            if count > 0:
                report(
                    "PII_REDACTED",
                    f"level={level.value} count={count}",
                    "[PII] Redacted %d %s items (%s)",
                    count,
                    level.value,
                    source,
                )
    return result


def apply_privacy_policy(text: str, policy: PrivacyPolicy, source: str, *, audit: bool = True) -> str:
    """Classify *text* and apply *policy* to it.

    A text that already exists (an AI response, a message about to be sent) cannot be refused, so a BLOCK action
    falls back to full redaction. A WARN action leaves the text as it is; every other rewrite is stable under
    repetition, so re-applying the policy to its own output changes nothing.
    """
    if not policy.enabled:
        return text
    level = classify_content(text, policy).level
    if level == SensitivityLevel.S1:
        return text
    processed = apply_pii_actions(text, levels_to_process(text, level, policy), policy, source, audit=audit)
    if processed is not None:
        return processed
    return redact_pii(text, custom_rules(policy, SensitivityLevel.S2, SensitivityLevel.S3))[0]
