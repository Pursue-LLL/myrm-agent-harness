"""Bank cards and mainland phone numbers as people type them: in groups ("4532 0151 1283 0366", "138 0013 8000").

The classifier, the redactor and the pseudonymizer share one pattern table, so each case below is checked at all three:
what a message is classified as, what the model is shown, and what comes back after the reply is restored.
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


@pytest.fixture()
def store(tmp_path: object) -> Generator[PseudonymStore]:
    pseudonym_store = PseudonymStore(os.path.join(str(tmp_path), "test_pseudonym.db"))
    yield pseudonym_store
    pseudonym_store.close()


class TestGroupedBankCard:
    @pytest.mark.parametrize(
        "text",
        [
            "卡号 4532 0151 1283 0366 请查收",
            "card 4532-0151-1283-0366",
            "银联 6222 0212 3456 7890 011",
            "6222-0212-3456-7890-011",
        ],
        ids=["spaced", "hyphenated", "unionpay-19-spaced", "unionpay-19-hyphenated"],
    )
    def test_a_card_typed_in_groups_is_confidential(self, text: str) -> None:
        result = classify_content(text, _ENABLED)
        assert result.level == SensitivityLevel.S3
        assert result.patterns == ["bank_card"]

    @pytest.mark.parametrize(
        "text",
        [
            "number 4444-555555555555",
            "number 4532-0151 1283-0366",
            "number 4532 0151\n1283 0366",
            "number 4532  0151  1283  0366",
            "id 12345678-1234-5678-1234-567812345678",
        ],
        ids=["uneven-groups", "mixed-separators", "line-break", "double-space", "uuid"],
    )
    def test_digits_that_only_look_like_a_grouped_card_are_not_confidential(self, text: str) -> None:
        assert classify_content(text, _ENABLED).level != SensitivityLevel.S3

    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            ("card 4532 0151 1283 0366 ok", "card **** **** **** 0366 [PII:bank_card] ok"),
            ("card 4532-0151-1283-0366 ok", "card **** **** **** 0366 [PII:bank_card] ok"),
            ("银联 6222 0212 3456 7890 011 ok", "银联 **** **** **** 0011 [PII:bank_card] ok"),
        ],
        ids=["spaced", "hyphenated", "unionpay-19"],
    )
    def test_a_card_typed_in_groups_is_masked_to_its_last_four_digits(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)

    @pytest.mark.parametrize("card", ["4532 0151 1283 0366", "4532-0151-1283-0366"], ids=["spaced", "hyphenated"])
    def test_a_card_typed_in_groups_is_replaced_and_restored_as_typed(self, store: PseudonymStore, card: str) -> None:
        result = pseudonymize_text(f"Card: {card}, thanks", store, SensitivityLevel.S3)

        assert result.text == "Card: <BANK_CARD_1>, thanks"
        assert store.resolve_all(result.text) == f"Card: {card}, thanks"

    def test_a_grouped_number_that_fails_the_luhn_check_is_not_a_bank_card(self, store: PseudonymStore) -> None:
        content = "Card: 4532 0151 1283 0367"

        assert classify_content(content, _ENABLED).level == SensitivityLevel.S2
        assert pseudonymize_text(content, store, SensitivityLevel.S3).text == content

    def test_a_masked_card_is_not_masked_again(self) -> None:
        once, _ = redact_pii("card 4532 0151 1283 0366 x")

        assert redact_pii(once) == (once, 0)


class TestGroupedChinaPhone:
    @pytest.mark.parametrize(
        "text",
        ["我的手机号 138 0013 8000", "手机 138-0013-8000", "call 138 0013-8000 please", "+86 138 0013 8000"],
        ids=["spaced", "hyphenated", "mixed", "country-code"],
    )
    def test_a_phone_typed_in_groups_is_sensitive(self, text: str) -> None:
        result = classify_content(text, _ENABLED)
        assert result.level == SensitivityLevel.S2
        assert "china_phone" in result.patterns

    @pytest.mark.parametrize(
        "text",
        [
            "编号 138 0013 80001",
            "编号 9138 0013 8000",
            "编号 138 0013 800",
            "编号 138  0013  8000",
            "编号 138\n0013\n8000",
            "编号 1380013800",
            "id dd75f159-9266-4208-995f-b71d8e2ed4d3",
            "id d1879671-3694-49ad-9da2-9080f1100854",
        ],
        ids=[
            "extra-digit",
            "leading-digit",
            "short",
            "double-space",
            "line-break",
            "ten-digits",
            "uuid-tail",
            "uuid-head",
        ],
    )
    def test_digits_that_only_look_like_a_grouped_phone_are_not_a_phone(self, text: str) -> None:
        assert classify_content(text, _ENABLED).level == SensitivityLevel.S1

    @pytest.mark.parametrize(
        "original",
        [
            "联系人 138 0013 8000 请回电",
            "联系人 138-0013-8000 请回电",
            "联系人 +86 138 0013 8000 请回电",
            "联系人 +86 13800138000 请回电",
        ],
        ids=["spaced", "hyphenated", "country-code-grouped", "country-code-contiguous"],
    )
    def test_masking_keeps_the_first_three_and_last_four_digits_of_the_number(self, original: str) -> None:
        assert redact_pii(original) == ("联系人 138****8000 [PII:phone] 请回电", 1)

    @pytest.mark.parametrize("phone", ["138 0013 8000", "138-0013-8000"], ids=["spaced", "hyphenated"])
    def test_a_phone_typed_in_groups_is_replaced_and_restored_as_typed(self, store: PseudonymStore, phone: str) -> None:
        result = pseudonymize_text(f"Call {phone} now", store, SensitivityLevel.S2)

        assert result.text == "Call <PHONE_NUMBER_1> now"
        assert store.resolve_all(result.text) == f"Call {phone} now"

    def test_a_masked_phone_is_not_masked_again(self) -> None:
        once, _ = redact_pii("tel +86 138 0013 8000 ok")

        assert redact_pii(once) == (once, 0)
