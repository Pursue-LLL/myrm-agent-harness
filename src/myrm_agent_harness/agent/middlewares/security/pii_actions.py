"""Per-level PII actions (warn, redact, pseudonymize, block) applied to a text under a PrivacyPolicy.

[INPUT]
- agent.security.types::PIIAction, PrivacyPolicy, SensitivityLevel (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)
- agent.security.detection.pii_classifier::classify_content (POS: Input-side PII classification engine. 30+ built-in regex patterns (bilingual CN/EN) with short-circuit optimization for efficient content scanning.)

[OUTPUT]
- levels_to_process: the sensitivity levels a detected level obliges the policy to act on
- apply_pii_actions: apply the policy action of each level to a text, audited unless ``audit=False``; None when a level blocks
- apply_privacy_policy: classify a text and apply the policy to it; a block becomes full redaction, so the text always comes back

[POS]
PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.middlewares._session_context import get_pseudonym_store
from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content
from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel

logger = logging.getLogger(__name__)


def levels_to_process(
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
                    report(
                        "PII_PSEUDONYMIZED",
                        f"level={level.value} count={ps_result.count}",
                        "[PII] Pseudonymized %d %s items (%s)",
                        ps_result.count,
                        level.value,
                        source,
                    )
            else:
                result, count = redact_pii(result)
                if count > 0:
                    report(
                        "PII_REDACTED",
                        f"level={level.value} count={count} (pseudonymize fallback)",
                        "[PII] Pseudonymize fallback to redact: %d items (%s)",
                        count,
                        source,
                    )
        elif action == PIIAction.REDACT:
            result, count = redact_pii(result)
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
    processed = apply_pii_actions(text, levels_to_process(level, policy), policy, source, audit=audit)
    return redact_pii(text)[0] if processed is None else processed
