"""preview_privacy_policy: what the model would see for a text, without touching any live state.

A settings page shows the preview next to the rules a user edits, so it must give the answer a real turn would give:
the same classification and the same per-level action, with pseudonyms and all, and it must leave nothing behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares._session_context import get_pseudonym_store, set_pseudonym_store
from myrm_agent_harness.agent.middlewares.security.pii_actions import apply_privacy_policy
from myrm_agent_harness.agent.middlewares.security.privacy_preview import preview_privacy_policy
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel
from myrm_agent_harness.core.security.audit import get_audit_entries, reset_audit_log
from myrm_agent_harness.core.security.detection import custom_rules as custom_rules_module

SENTENCE = "帮我总结凤凰计划Q3预算超支原因，发给李总"


def _policy(
    s2: PIIAction = PIIAction.WARN,
    s3: PIIAction = PIIAction.REDACT,
    *,
    custom_keywords_s2: tuple[str, ...] = (),
    custom_keywords_s3: tuple[str, ...] = (),
    custom_patterns_s2: tuple[str, ...] = (),
    custom_patterns_s3: tuple[str, ...] = (),
) -> PrivacyPolicy:
    return PrivacyPolicy(
        enabled=True,
        s2_action=s2,
        s3_action=s3,
        custom_keywords_s2=custom_keywords_s2,
        custom_keywords_s3=custom_keywords_s3,
        custom_patterns_s2=custom_patterns_s2,
        custom_patterns_s3=custom_patterns_s3,
    )


@pytest.fixture(autouse=True)
def _clean_state() -> Iterator[None]:
    reset_audit_log()
    set_pseudonym_store(None)
    yield
    set_pseudonym_store(None)


class TestPreview:
    def test_an_s3_keyword_is_redacted_in_what_the_model_sees(self) -> None:
        preview = preview_privacy_policy(SENTENCE, _policy(custom_keywords_s3=("凤凰计划",)))

        assert preview.level == SensitivityLevel.S3
        assert preview.action == PIIAction.REDACT
        assert preview.model_sees == "帮我总结[REDACTED] [PII:custom]Q3预算超支原因，发给李总"

    def test_an_s2_keyword_with_a_warn_action_goes_through_unchanged(self) -> None:
        preview = preview_privacy_policy(SENTENCE, _policy(custom_keywords_s2=("凤凰计划",)))

        assert preview.level == SensitivityLevel.S2
        assert preview.action == PIIAction.WARN
        assert preview.model_sees == SENTENCE

    def test_a_pseudonymized_term_shows_its_tag(self) -> None:
        preview = preview_privacy_policy(SENTENCE, _policy(s3=PIIAction.PSEUDONYMIZE, custom_keywords_s3=("凤凰计划",)))

        assert preview.action == PIIAction.PSEUDONYMIZE
        assert preview.model_sees == "帮我总结<CUSTOM_KEYWORD_1>Q3预算超支原因，发给李总"

    def test_a_blocked_text_is_never_sent(self) -> None:
        preview = preview_privacy_policy(SENTENCE, _policy(s3=PIIAction.BLOCK, custom_keywords_s3=("凤凰计划",)))

        assert preview.level == SensitivityLevel.S3
        assert preview.action == PIIAction.BLOCK
        assert preview.model_sees is None

    def test_a_clean_text_has_no_action(self) -> None:
        preview = preview_privacy_policy("今天天气不错，适合散步", _policy(custom_keywords_s3=("凤凰计划",)))

        assert preview.level == SensitivityLevel.S1
        assert preview.action is None
        assert preview.model_sees == "今天天气不错，适合散步"

    def test_built_in_detectors_show_in_the_preview_too(self) -> None:
        preview = preview_privacy_policy("我的手机号是13812345678", _policy(s2=PIIAction.REDACT))

        assert preview.level == SensitivityLevel.S2
        assert preview.model_sees == "我的手机号是138****5678 [PII:phone]"

    def test_the_preview_is_what_a_real_turn_sends(self) -> None:
        policy = _policy(custom_keywords_s3=("凤凰计划",), custom_patterns_s2=(r"EMP-\d{6}",), s2=PIIAction.REDACT)
        text = f"{SENTENCE}，EMP-123456 负责"

        assert preview_privacy_policy(text, policy).model_sees == apply_privacy_policy(text, policy, "t", audit=False)

    def test_a_disabled_policy_changes_nothing(self) -> None:
        preview = preview_privacy_policy(SENTENCE, PrivacyPolicy(enabled=False, custom_keywords_s3=("凤凰计划",)))

        assert preview.level == SensitivityLevel.S1
        assert preview.model_sees == SENTENCE


class TestNoLiveState:
    def test_no_audit_entry_is_written(self) -> None:
        preview_privacy_policy(SENTENCE, _policy(custom_keywords_s3=("凤凰计划",)))

        assert get_audit_entries() == []

    def test_the_live_pseudonym_store_is_neither_used_nor_replaced(self, tmp_path: Path) -> None:
        live = PseudonymStore(str(tmp_path / "live.db"))
        set_pseudonym_store(live)

        preview_privacy_policy(SENTENCE, _policy(s3=PIIAction.PSEUDONYMIZE, custom_keywords_s3=("凤凰计划",)))

        assert get_pseudonym_store() is live
        assert live.stats() == {}
        live.close()

    def test_repeated_previews_give_the_same_tag(self) -> None:
        policy = _policy(s3=PIIAction.PSEUDONYMIZE, custom_keywords_s3=("凤凰计划",))

        first = preview_privacy_policy(SENTENCE, policy)
        second = preview_privacy_policy(SENTENCE, policy)

        assert first == second


class TestIneffectivePatterns:
    """A pattern that cannot be used protects nothing, so the settings page must be told which ones those are."""

    def test_a_pattern_that_cannot_be_used_is_named_whatever_its_level(self) -> None:
        policy = _policy(custom_patterns_s2=("([",), custom_patterns_s3=("a{99999999999}", r"EMP-\d{6}"))

        assert preview_privacy_policy(SENTENCE, policy).ineffective_patterns == ("([", "a{99999999999}")

    def test_a_pattern_too_large_to_build_is_named_and_never_built(self) -> None:
        policy = _policy(custom_patterns_s3=(r"a{10000000}", r"EMP-\d{6}"))

        assert preview_privacy_policy(SENTENCE, policy).ineffective_patterns == (r"a{10000000}",)

    def test_sound_patterns_are_not_named(self) -> None:
        policy = _policy(custom_patterns_s3=(r"EMP-\d{6}", r"\p{Han}{2,4}科技"))

        assert preview_privacy_policy(SENTENCE, policy).ineffective_patterns == ()

    def test_the_patterns_are_named_for_a_text_with_nothing_to_hide_and_for_no_text(self) -> None:
        policy = _policy(custom_patterns_s3=("([",))

        assert preview_privacy_policy("今天天气不错", policy).ineffective_patterns == ("([",)
        assert preview_privacy_policy("", policy).ineffective_patterns == ("([",)

    def test_the_patterns_are_named_next_to_what_the_working_rules_hide(self) -> None:
        policy = _policy(custom_keywords_s3=("凤凰计划",), custom_patterns_s3=("([",))

        preview = preview_privacy_policy(SENTENCE, policy)

        assert preview.model_sees == "帮我总结[REDACTED] [PII:custom]Q3预算超支原因，发给李总"
        assert preview.ineffective_patterns == ("([",)

    def test_a_disabled_policy_has_no_rules_to_report(self) -> None:
        policy = PrivacyPolicy(enabled=False, custom_patterns_s3=("([",))

        assert preview_privacy_policy(SENTENCE, policy).ineffective_patterns == ()


class TestPatternThatCannotFinish:
    """The whole text counts as the hit, so every action treats it as it would a text the pattern had matched."""

    _TEXT = "a" * 60 + "!"

    @pytest.fixture(autouse=True)
    def _short_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(custom_rules_module, "_PATTERN_TIMEOUT_SECONDS", 0.05)

    @pytest.mark.parametrize(
        ("action", "model_sees"),
        [
            (PIIAction.REDACT, "[REDACTED] [PII:custom]"),
            (PIIAction.PSEUDONYMIZE, "<CUSTOM_PATTERN_1>"),
            (PIIAction.BLOCK, None),
            (PIIAction.WARN, _TEXT),
        ],
    )
    def test_the_action_applies_to_the_whole_text(self, action: PIIAction, model_sees: str | None) -> None:
        preview = preview_privacy_policy(self._TEXT, _policy(s3=action, custom_patterns_s3=(r"(a|aa)+$",)))

        assert preview.level == SensitivityLevel.S3
        assert preview.action == action
        assert preview.model_sees == model_sees
        assert preview.ineffective_patterns == ()
