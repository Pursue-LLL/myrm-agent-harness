"""Each sensitivity level acts only on what it covers.

A message that holds several levels at once (a card number next to a phone number and an e-mail address) is handled
level by level: the action a user picked for S2 never touches S3 content and the other way round, and a level whose
action is BLOCK stops the message only when the message holds that level.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent.middlewares._session_context import set_pseudonym_store
from myrm_agent_harness.agent.middlewares.security.pii_actions import (
    apply_privacy_policy,
    blocking_level,
    levels_to_process,
)
from myrm_agent_harness.agent.middlewares.security.privacy_preview import preview_privacy_policy
from myrm_agent_harness.agent.middlewares.security.user_input_guard import screen_user_input
from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SensitivityLevel

CARD = "4532015112830366"
PHONE = "13800138000"
EMAIL = "bob@corp.com"
MIXED = f"卡号 {CARD}，电话 {PHONE}，邮箱 {EMAIL}"

S2 = SensitivityLevel.S2
S3 = SensitivityLevel.S3


def _policy(s2: PIIAction, s3: PIIAction) -> PrivacyPolicy:
    return PrivacyPolicy(enabled=True, s2_action=s2, s3_action=s3)


@pytest.fixture(autouse=True)
def _no_store() -> Iterator[None]:
    set_pseudonym_store(None)
    yield
    set_pseudonym_store(None)


def _screened(text: str, policy: PrivacyPolicy) -> str:
    """What the model is shown for *text* as the user's latest message."""
    screened = screen_user_input([HumanMessage(content=text)], policy)
    content = text if screened is None else screened[0].content
    assert isinstance(content, str)
    return content


class TestEachLevelActsOnlyOnItsOwnContent:
    def test_a_warn_level_keeps_its_content_next_to_a_redacted_one(self) -> None:
        text = apply_privacy_policy(MIXED, _policy(PIIAction.WARN, PIIAction.REDACT), "t")

        assert CARD not in text
        assert PHONE in text
        assert EMAIL in text

    def test_a_redacted_s2_leaves_the_s3_content_to_the_s3_action(self) -> None:
        text = apply_privacy_policy(MIXED, _policy(PIIAction.REDACT, PIIAction.WARN), "t")

        assert CARD in text
        assert PHONE not in text
        assert EMAIL not in text

    def test_a_redacted_s2_leaves_a_password_to_the_s3_action(self) -> None:
        text = apply_privacy_policy(
            "密码：Zk9%mango42 电话 13800138000", _policy(PIIAction.REDACT, PIIAction.WARN), "t"
        )

        assert "Zk9%mango42" in text
        assert PHONE not in text

    def test_a_pseudonymized_s2_is_restored_next_to_a_redacted_s3(self, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "ps.db"))
        set_pseudonym_store(store)

        text = apply_privacy_policy(MIXED, _policy(PIIAction.PSEUDONYMIZE, PIIAction.REDACT), "t")

        assert CARD not in text
        assert "<PHONE_NUMBER_1>" in text
        assert "<EMAIL_ADDRESS_1>" in text
        assert store.resolve_all(text) == f"卡号 **** **** **** 0366 [PII:bank_card]，电话 {PHONE}，邮箱 {EMAIL}"
        store.close()

    def test_the_fallback_of_a_pseudonymizing_level_without_a_store_stays_inside_its_level(self) -> None:
        text = apply_privacy_policy(MIXED, _policy(PIIAction.PSEUDONYMIZE, PIIAction.WARN), "t")

        assert CARD in text
        assert PHONE not in text


class TestRedactPiiLevels:
    def test_the_s3_level_masks_only_confidential_content(self) -> None:
        text, count = redact_pii(MIXED, levels=frozenset({S3}))

        assert (CARD not in text, PHONE in text, EMAIL in text) == (True, True, True)
        assert count == 1

    def test_the_s2_level_masks_only_sensitive_content(self) -> None:
        text, count = redact_pii(MIXED, levels=frozenset({S2}))

        assert (CARD in text, PHONE not in text, EMAIL not in text) == (True, True, True)
        assert count == 2

    def test_every_level_is_masked_unless_the_caller_narrows_it(self) -> None:
        text, count = redact_pii(MIXED)

        assert all(value not in text for value in (CARD, PHONE, EMAIL))
        assert count == 3


class TestLevelsToProcess:
    def test_s2_joins_a_detected_s3_when_its_action_acts_and_the_text_holds_it(self) -> None:
        policy = _policy(PIIAction.REDACT, PIIAction.REDACT)

        assert levels_to_process(MIXED, S3, policy) == [S3, S2]

    def test_s2_does_not_join_a_text_that_holds_no_s2_content(self) -> None:
        policy = _policy(PIIAction.BLOCK, PIIAction.REDACT)

        assert levels_to_process(f"卡号 {CARD}", S3, policy) == [S3]

    def test_s2_does_not_join_when_its_action_is_warn(self) -> None:
        policy = _policy(PIIAction.WARN, PIIAction.REDACT)

        assert levels_to_process(MIXED, S3, policy) == [S3]

    def test_a_detected_s2_stands_alone(self) -> None:
        policy = _policy(PIIAction.REDACT, PIIAction.REDACT)

        assert levels_to_process(f"电话 {PHONE}", S2, policy) == [S2]


class TestABlockNeedsTheLevelToBePresent:
    """A user who blocks S2 and only redacts S3 still sends a message that holds a card and nothing else."""

    policy = _policy(PIIAction.BLOCK, PIIAction.REDACT)

    def test_a_card_alone_is_redacted_not_blocked(self) -> None:
        shown = _screened(f"我的银行卡 {CARD} 帮我记一下", self.policy)

        assert not shown.startswith("[BLOCKED]")
        assert CARD not in shown
        assert "[PII:bank_card]" in shown

    def test_s2_content_alone_is_blocked_at_s2(self) -> None:
        shown = _screened(f"我的手机 {PHONE} 帮我记一下", self.policy)

        assert shown.startswith("[BLOCKED]")
        assert "s2-level" in shown

    def test_s2_content_next_to_a_card_blocks_the_message_at_s2(self) -> None:
        shown = _screened(MIXED, self.policy)

        assert shown.startswith("[BLOCKED]")
        assert "s2-level" in shown

    def test_a_blocked_s3_is_named_s3(self) -> None:
        shown = _screened(MIXED, _policy(PIIAction.REDACT, PIIAction.BLOCK))

        assert shown.startswith("[BLOCKED]")
        assert "s3-level" in shown

    def test_the_settings_preview_says_what_a_real_turn_does(self) -> None:
        card_only = preview_privacy_policy(f"卡号 {CARD}", self.policy)
        mixed = preview_privacy_policy(MIXED, self.policy)

        assert card_only.action == PIIAction.REDACT
        assert card_only.model_sees is not None
        assert CARD not in card_only.model_sees
        assert mixed.action == PIIAction.BLOCK
        assert mixed.model_sees is None

    def test_the_settings_preview_names_the_level_that_blocks(self) -> None:
        """The level shown next to a block is the one a real turn reports, not the text's highest level."""
        mixed = preview_privacy_policy(MIXED, self.policy)
        s3_blocks = preview_privacy_policy(MIXED, _policy(PIIAction.REDACT, PIIAction.BLOCK))

        assert (mixed.level, mixed.action) == (S2, PIIAction.BLOCK)
        assert (s3_blocks.level, s3_blocks.action) == (S3, PIIAction.BLOCK)


class TestBlockingLevel:
    def test_the_first_level_whose_action_is_block_refuses_the_text(self) -> None:
        assert blocking_level(_policy(PIIAction.BLOCK, PIIAction.BLOCK), [S3, S2]) == S3
        assert blocking_level(_policy(PIIAction.BLOCK, PIIAction.REDACT), [S3, S2]) == S2

    def test_no_level_blocks_when_none_of_the_actions_is_block(self) -> None:
        assert blocking_level(_policy(PIIAction.WARN, PIIAction.REDACT), [S3, S2]) is None
        assert blocking_level(_policy(PIIAction.BLOCK, PIIAction.BLOCK), []) is None


class TestACardKeywordFollowsTheSamePolicy:
    """A card number a keyword introduces is S3 content like any other: the default policy masks it."""

    NUMBER = "6759649826438453"  # Maestro: no prefix-table network, valid Luhn

    def test_the_default_policy_masks_it_in_a_user_message(self) -> None:
        shown = _screened(f"银行卡号 {self.NUMBER} 帮我记一下", PrivacyPolicy(enabled=True))

        assert self.NUMBER not in shown
        assert "[PII:bank_card]" in shown

    def test_pseudonymization_replaces_it_with_a_bank_card_tag(self, tmp_path: Path) -> None:
        store = PseudonymStore(str(tmp_path / "p.db"))
        set_pseudonym_store(store)
        try:
            shown = apply_privacy_policy(
                f"card number {self.NUMBER}", _policy(PIIAction.WARN, PIIAction.PSEUDONYMIZE), "t"
            )
        finally:
            store.close()

        assert self.NUMBER not in shown
        assert "BANK_CARD" in shown
