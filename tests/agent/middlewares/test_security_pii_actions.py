"""apply_pii_actions: one rewrite, with or without an audit trail.

The guard applies the policy to earlier user messages on every model call. Those rewrites repeat what was recorded
when the message was new, so they must not add audit entries, log lines or metrics a second time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares._session_context import set_pseudonym_store
from myrm_agent_harness.agent.middlewares.security.pii_actions import apply_pii_actions, apply_privacy_policy
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel
from myrm_agent_harness.core.security.audit import get_audit_entries, reset_audit_log

TEXT = "call 13812345678 please"
LEVELS = [SensitivityLevel.S2]


@pytest.fixture(autouse=True)
def _clean_session() -> Iterator[None]:
    reset_audit_log()
    set_pseudonym_store(None)
    yield
    set_pseudonym_store(None)


def _policy(action: PIIAction) -> PrivacyPolicy:
    return PrivacyPolicy(enabled=True, s2_action=action, s3_action=action)


class TestSilentMode:
    @pytest.mark.parametrize("action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE], ids=["redact", "pseudonymize"])
    def test_the_text_is_the_same_with_and_without_audit(self, action: PIIAction, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)

        audited = apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input")
        silent = apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input", audit=False)

        assert silent == audited
        assert silent is not None
        assert "13812345678" not in silent
        store.close()

    @pytest.mark.parametrize(
        "action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE], ids=["redact", "pseudonymize-fallback"]
    )
    def test_a_silent_rewrite_leaves_no_audit_entry_and_no_log_line(
        self, action: PIIAction, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input", audit=False)

        assert get_audit_entries() == []
        assert not [record for record in caplog.records if "[PII]" in record.getMessage()]

    @pytest.mark.parametrize(
        "action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE], ids=["redact", "pseudonymize-fallback"]
    )
    def test_an_audited_rewrite_leaves_both(self, action: PIIAction, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            apply_pii_actions(TEXT, LEVELS, _policy(action), "user_input")

        assert len(get_audit_entries()) == 1
        assert [record for record in caplog.records if "[PII]" in record.getMessage()]

    def test_the_pseudonym_is_audited_only_when_asked(self, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)

        apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.PSEUDONYMIZE), "user_input", audit=False)
        assert get_audit_entries() == []

        apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.PSEUDONYMIZE), "user_input")
        assert [entry.decision for entry in get_audit_entries()] == ["PII_PSEUDONYMIZED"]
        store.close()

    def test_a_block_is_the_same_with_and_without_audit(self) -> None:
        assert apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.BLOCK), "user_input") is None
        assert apply_pii_actions(TEXT, LEVELS, _policy(PIIAction.BLOCK), "user_input", audit=False) is None


_SENTENCE = "帮我总结凤凰计划Q3预算超支原因，发给李总"


def _custom_policy(
    s2: PIIAction,
    s3: PIIAction,
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


class TestCustomRules:
    """The custom keywords and patterns a user lists are masked by the action chosen for their level."""

    def test_an_s3_keyword_is_redacted_inside_a_chinese_sentence(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.REDACT, custom_keywords_s3=("凤凰计划",))

        assert apply_privacy_policy(_SENTENCE, policy, "t") == "帮我总结[REDACTED] [PII:custom]Q3预算超支原因，发给李总"

    def test_a_bare_keyword_is_redacted(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.REDACT, custom_keywords_s3=("凤凰计划",))

        assert apply_privacy_policy("凤凰计划", policy, "t") == "[REDACTED] [PII:custom]"

    def test_a_warn_action_leaves_the_text_alone(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.WARN, custom_keywords_s3=("凤凰计划",))

        assert apply_privacy_policy(_SENTENCE, policy, "t") == _SENTENCE

    def test_an_s2_keyword_follows_the_s2_action(self) -> None:
        policy = _custom_policy(PIIAction.REDACT, PIIAction.BLOCK, custom_keywords_s2=("凤凰计划",))

        assert "凤凰计划" not in apply_privacy_policy(_SENTENCE, policy, "t")

    def test_an_s2_keyword_with_a_warn_action_survives_next_to_an_s3_hit(self) -> None:
        policy = _custom_policy(
            PIIAction.WARN, PIIAction.REDACT, custom_keywords_s2=("凤凰计划",), custom_keywords_s3=("绝密",)
        )

        text = apply_privacy_policy("绝密：凤凰计划 Q3 预算", policy, "t")

        assert "绝密" not in text
        assert "凤凰计划" in text

    def test_an_s2_keyword_with_a_redact_action_is_masked_next_to_an_s3_hit(self) -> None:
        policy = _custom_policy(
            PIIAction.REDACT, PIIAction.REDACT, custom_keywords_s2=("凤凰计划",), custom_keywords_s3=("绝密",)
        )

        text = apply_privacy_policy("绝密：凤凰计划 Q3 预算", policy, "t")

        assert "绝密" not in text
        assert "凤凰计划" not in text

    def test_a_pattern_is_redacted(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.REDACT, custom_patterns_s3=(r"EMP-\d{6}",))

        assert apply_privacy_policy("EMP-123456 在休假", policy, "t") == "[REDACTED] [PII:custom] 在休假"

    def test_a_pseudonymized_keyword_restores_through_the_store(self, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)
        policy = _custom_policy(PIIAction.WARN, PIIAction.PSEUDONYMIZE, custom_keywords_s3=("凤凰计划",))

        masked = apply_privacy_policy(_SENTENCE, policy, "t")

        assert masked == "帮我总结<CUSTOM_KEYWORD_1>Q3预算超支原因，发给李总"
        assert store.resolve_all(masked) == _SENTENCE
        store.close()

    def test_pseudonymizing_without_a_store_falls_back_to_redaction(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.PSEUDONYMIZE, custom_keywords_s3=("凤凰计划",))

        assert "凤凰计划" not in apply_privacy_policy(_SENTENCE, policy, "t")

    def test_a_block_action_still_returns_a_fully_redacted_text(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.BLOCK, custom_keywords_s3=("凤凰计划",))

        text = apply_privacy_policy("凤凰计划，电话 13812345678", policy, "t")

        assert "凤凰计划" not in text
        assert "13812345678" not in text

    def test_a_block_is_reported_to_the_caller_of_apply_pii_actions(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.BLOCK, custom_keywords_s3=("凤凰计划",))

        assert apply_pii_actions(_SENTENCE, [SensitivityLevel.S3], policy, "t") is None

    @pytest.mark.parametrize("action", [PIIAction.REDACT, PIIAction.PSEUDONYMIZE, PIIAction.BLOCK])
    def test_applying_the_policy_to_its_own_output_changes_nothing(self, action: PIIAction, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)
        policy = _custom_policy(
            PIIAction.WARN, action, custom_keywords_s3=("凤凰计划",), custom_patterns_s3=(r"EMP-\d{6}",)
        )

        once = apply_privacy_policy("凤凰计划：EMP-123456 的 Q3 预算，凤凰计划二期", policy, "t")

        assert apply_privacy_policy(once, policy, "t") == once
        store.close()

    def test_rules_that_are_not_configured_change_nothing(self) -> None:
        policy = _custom_policy(PIIAction.WARN, PIIAction.REDACT)

        assert apply_privacy_policy(_SENTENCE, policy, "t") == _SENTENCE
