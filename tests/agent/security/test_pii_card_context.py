"""A card number the text introduces as a card is confidential whatever network issued it.

The prefix table knows the major networks; a Maestro, Mir, RuPay or Troy number, or one with a typo in it, matches no
prefix or fails the Luhn check, yet "银行卡号 …" and "card number is …" leave no doubt about what the digits are.
Each case below is checked at the classifier, the redactor and the pseudonymizer.
"""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest

from myrm_agent_harness.agent.security.detection.pii_classifier import classify_content
from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.agent.security.detection.pseudonymizer import pseudonymize_text
from myrm_agent_harness.agent.security.types import PrivacyPolicy, SensitivityLevel

_ENABLED = PrivacyPolicy(enabled=True)

# Numbers of networks outside the prefix table, and a Visa with a typo (it fails the Luhn check).
_NUMBERS = {
    "maestro": "6759649826438453",
    "maestro-5018": "5018000000000009",
    "mir": "2200000000000053",
    "rupay": "6521000000000001",
    "troy": "9792000000000001",
    "visa-typo": "4532015112830367",
    "thirteen-digits": "6759000000001",
    "nineteen-digits": "6759000000000000001",
}


@pytest.fixture()
def store(tmp_path: object) -> Generator[PseudonymStore]:
    pseudonym_store = PseudonymStore(os.path.join(str(tmp_path), "test_pseudonym.db"))
    yield pseudonym_store
    pseudonym_store.close()


class TestClassified:
    @pytest.mark.parametrize("number", _NUMBERS.values(), ids=_NUMBERS.keys())
    def test_a_number_introduced_as_a_card_is_confidential(self, number: str) -> None:
        result = classify_content(f"card number is {number} thanks", _ENABLED)

        assert result.level == SensitivityLevel.S3
        assert result.patterns == ["bank_card_context"]

    @pytest.mark.parametrize(
        "introduction",
        [
            "银行卡号：",
            "银行卡 ",
            "信用卡号是",
            "我的储蓄卡 ",
            "借记卡：",
            "卡号 ",
            "Bank card: ",
            "my credit card number is ",
            "DEBIT CARD ",
            "Card number: ",
            "Card No. ",
            "card no ",
            "bank card (Maestro) ",
        ],
    )
    def test_the_introduction_may_be_in_either_language(self, introduction: str) -> None:
        result = classify_content(f"{introduction}6759649826438453 谢谢", _ENABLED)

        assert result.level == SensitivityLevel.S3
        assert result.patterns == ["bank_card_context"]

    @pytest.mark.parametrize("number", ["6759 6498 2643 8453", "6759-6498-2643-8453", "5018 123456 12345"])
    def test_a_number_typed_in_groups_is_confidential(self, number: str) -> None:
        result = classify_content(f"card number: {number} ok", _ENABLED)

        assert result.level == SensitivityLevel.S3
        assert result.patterns == ["bank_card_context"]

    def test_a_card_of_a_known_network_is_still_found_by_its_prefix(self) -> None:
        assert classify_content("card number is 4532015112830366", _ENABLED).patterns == ["bank_card"]

    @pytest.mark.parametrize(
        "text",
        [
            "card 6759649826438453",
            "Card: 4532 0151 1283 0367",
            "discard number 6759649826438453",
            "member card number 123456789012",
            "card number 12345678901234567890",
            "card number 4 of 12",
            "card number 6759-6498-2643-845",
            "bank card hotline 4001234567",
            "银行卡预留手机号 13800138000",
            "bank card\n6759649826438453",
            "bank card is the topic of this rather long sentence 6759649826438453",
            "the number 6759649826438453 is not introduced as a card",
        ],
        ids=[
            "bare-card",
            "bare-card-grouped",
            "keyword-inside-a-word",
            "twelve-digits",
            "twenty-digits",
            "short-number",
            "unfinished-group",
            "phone-hotline",
            "phone",
            "line-break",
            "too-far",
            "no-introduction",
        ],
    )
    def test_digits_that_are_not_introduced_as_a_card_number_are_not_confidential(self, text: str) -> None:
        assert classify_content(text, _ENABLED).level != SensitivityLevel.S3


class TestExpiryAndCvvAfterTheNumber:
    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            (
                "card number 6759 6498 2643 8453 12/28",
                "card number **** **** **** 8453 [PII:bank_card] 12/28",
            ),
            (
                "card number 6759649826438453, cvv 123",
                "card number **** **** **** 8453 [PII:bank_card], cvv 123",
            ),
            (
                "银行卡号 6759-6498-2643-8453 有效期 12/28",
                "银行卡号 **** **** **** 8453 [PII:bank_card] 有效期 12/28",
            ),
        ],
        ids=["spaced-expiry", "contiguous-cvv", "hyphenated-expiry"],
    )
    def test_only_the_number_is_masked(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)


class TestRedacted:
    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            ("card number is 6759649826438453 ok", "card number is **** **** **** 8453 [PII:bank_card] ok"),
            ("银行卡号 4532015112830367 谢谢", "银行卡号 **** **** **** 0367 [PII:bank_card] 谢谢"),
            ("card number: 5018 123456 12345 ok", "card number: **** **** **** 2345 [PII:bank_card] ok"),
        ],
        ids=["maestro", "visa-typo", "four-six-five"],
    )
    def test_a_number_introduced_as_a_card_is_masked_to_its_last_four_digits(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)

    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            ("card number 4532015112830366", "card number **** **** **** 0366 [PII:bank_card]"),
            ("银行卡 6222 0212 3456 7890 011", "银行卡 **** **** **** 0011 [PII:bank_card]"),
            ("信用卡号 3782 822463 10005", "信用卡号 **** **** **** 0005 [PII:bank_card]"),
        ],
        ids=["visa", "unionpay-19", "amex-typed"],
    )
    def test_a_card_found_by_its_prefix_is_masked_once(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)

    def test_it_belongs_to_the_confidential_level(self) -> None:
        text = "card number is 6759649826438453"

        assert redact_pii(text, levels=frozenset({SensitivityLevel.S2})) == (text, 0)
        assert redact_pii(text, levels=frozenset({SensitivityLevel.S3})) == (
            "card number is **** **** **** 8453 [PII:bank_card]",
            1,
        )

    def test_it_is_a_bank_card_and_not_a_visible_card_when_both_levels_are_redacted(self) -> None:
        # Typed in fours the number also fits the visible-card rule of the sensitive level; the confidential
        # level goes first, so the number is masked once and as a bank card.
        masked, count = redact_pii("card number is 6759 6498 2643 8453")

        assert masked == "card number is **** **** **** 8453 [PII:bank_card]"
        assert count == 1

    @pytest.mark.parametrize(
        "text",
        [
            "card number is 6759649826438453 ok",
            "银行卡号 4532015112830367 谢谢",
            "card number 6759 6498 2643 8453 12/28",
            "银行卡 6222 0212 3456 7890 011",
        ],
    )
    def test_a_second_pass_changes_nothing(self, text: str) -> None:
        once, _ = redact_pii(text)

        twice, count = redact_pii(once)

        assert twice == once
        assert count == 0


class TestPseudonymized:
    @pytest.mark.parametrize("number", ["6759649826438453", "4532015112830367", "6759 6498 2643 8453"])
    def test_a_number_introduced_as_a_card_is_replaced_and_restored_as_typed(
        self, store: PseudonymStore, number: str
    ) -> None:
        text = f"Card number is {number}, thanks"

        result = pseudonymize_text(text, store, SensitivityLevel.S3)

        assert result.text == "Card number is <BANK_CARD_1>, thanks"
        assert store.resolve_all(result.text) == text

    @pytest.mark.parametrize(
        "text",
        [
            "银行卡 6222 0212 3456 7890 011",
            "card number 4532015112830366",
            "信用卡号 3782 822463 10005",
        ],
    )
    def test_a_card_found_by_its_prefix_is_replaced_once(self, store: PseudonymStore, text: str) -> None:
        result = pseudonymize_text(text, store, SensitivityLevel.S3)

        assert result.count == 1
        assert result.text.endswith("<BANK_CARD_1>")
        assert store.resolve_all(result.text) == text

    def test_only_the_number_is_replaced(self, store: PseudonymStore) -> None:
        text = "card number 6759649826438453 expires 12/28"

        result = pseudonymize_text(text, store, SensitivityLevel.S3)

        assert result.text == "card number <BANK_CARD_1> expires 12/28"
        assert store.resolve_all(result.text) == text
