"""Per-level PII actions (warn, redact, pseudonymize, block) applied to a text under a PrivacyPolicy.

[INPUT]
- agent.security.types::PIIAction, PrivacyPolicy, SensitivityLevel (POS: Foundation layer of the security type hierarchy. All other security modules import from here; this module imports from none of them.)

[OUTPUT]
- levels_to_process: the sensitivity levels a detected level obliges the policy to act on
- apply_pii_actions: apply the policy action of each level to a text; None when a level blocks

[POS]
PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.agent.middlewares._session_context import get_pseudonym_store
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
