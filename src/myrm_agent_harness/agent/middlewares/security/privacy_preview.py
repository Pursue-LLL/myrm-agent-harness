"""What the model would see for a text under a privacy policy, computed without touching any live state.

[INPUT]
- agent.middlewares.security.pii_actions::apply_pii_actions, levels_to_process (POS: PII action engine shared by the guardrail's input and output layers and by the tool-result PII guard.)
- agent.middlewares._session_context::get_pseudonym_store, set_pseudonym_store (POS: Context-local session state of the security middlewares.)
- agent.security.detection.pii_classifier::classify_content (POS: Input-side PII classification engine.)
- agent.security.detection.pseudonym_store::PseudonymStore (POS: Persistent mapping between original sensitive text and its pseudonym tag.)
- agent.security.types::PIIAction, PrivacyPolicy, SensitivityLevel (POS: Foundation layer of the security type hierarchy.)

[OUTPUT]
- PrivacyPreview: detected level, the action the policy takes at that level, and the text the model would receive
- preview_privacy_policy: classify a text and apply the policy to it the way a real turn does, as a pure function

[POS]
Dry run of the privacy layer for a settings page: the same classification and the same per-level action a chat turn
applies, so the answer is the turn's answer. Nothing is recorded: no audit entry, and a pseudonymizing policy writes
its tags to a throwaway store, so the user's real pseudonym mapping never learns a text that was only being tried.
The regex layer is what is previewed; the LLM deep scan is not run.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.middlewares._session_context import get_pseudonym_store, set_pseudonym_store
from myrm_agent_harness.agent.middlewares.security.pii_actions import apply_pii_actions, levels_to_process
from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel

_PREVIEW_SOURCE = "privacy_preview"


@dataclass(frozen=True, slots=True)
class PrivacyPreview:
    """Outcome of a dry run. ``action`` is None for a text with nothing sensitive; ``model_sees`` is None when the
    policy blocks the text, which a real turn refuses to send at all."""

    level: SensitivityLevel
    action: PIIAction | None
    model_sees: str | None


def _action_at(policy: PrivacyPolicy, level: SensitivityLevel) -> PIIAction:
    return policy.s3_action if level == SensitivityLevel.S3 else policy.s2_action


@contextmanager
def _throwaway_pseudonym_store() -> Iterator[None]:
    """Make a scratch store the session's store, then put the previous one back and discard the scratch."""
    with tempfile.TemporaryDirectory(prefix="privacy-preview-") as scratch:
        store = PseudonymStore(str(Path(scratch) / "preview.db"))
        live = get_pseudonym_store()
        set_pseudonym_store(store)
        try:
            yield
        finally:
            set_pseudonym_store(live)
            store.close()


def preview_privacy_policy(text: str, policy: PrivacyPolicy) -> PrivacyPreview:
    """Classify *text* and apply *policy* to it as a real turn does, leaving no trace."""
    if not policy.enabled:
        return PrivacyPreview(SensitivityLevel.S1, None, text)
    level = classify_content(text, policy).level
    if level == SensitivityLevel.S1:
        return PrivacyPreview(level, None, text)
    levels = levels_to_process(level, policy)
    pseudonymizes = any(_action_at(policy, lv) == PIIAction.PSEUDONYMIZE for lv in levels)
    with _throwaway_pseudonym_store() if pseudonymizes else nullcontext():
        model_sees = apply_pii_actions(text, levels, policy, _PREVIEW_SOURCE, audit=False)
    return PrivacyPreview(level, _action_at(policy, level), model_sees)
