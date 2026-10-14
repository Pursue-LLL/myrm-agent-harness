"""Bank cards of every major network are confidential, in whatever way a person types them.

One brand table drives the classifier, the redactor and the pseudonymizer, so each case below is checked at all three:
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

# Luhn-valid test numbers, one per network (and per edge of a network's prefix range).
_CARDS = {
    "visa": "4532015112830366",
    "mastercard-5-series": "5555555555554444",
    "mastercard-2-series-first": "2221000000000009",
    "mastercard-2-series": "2223003122003222",
    "mastercard-2-series-last": "2720999999999996",
    "amex": "378282246310005",
    "jcb-first": "3528000000000007",
    "jcb": "3566002020360505",
    "jcb-last": "3589000000000003",
    "discover-6011": "6011111111111117",
    "discover-644": "6440000000000005",
    "discover-649": "6490000000000004",
    "discover-65": "6500000000000002",
    "unionpay": "6200000000000005",
    "unionpay-19": "6222021234567890011",
}

# Luhn-valid numbers just outside every network's prefix range: not a card number of any network.
_OUT_OF_RANGE = {
    "below-mastercard-2-series": "2220000000000000",
    "above-mastercard-2-series": "2721000000000004",
    "below-jcb": "3500000000000009",
    "below-discover": "6000000000000007",
}


@pytest.fixture()
def store(tmp_path: object) -> Generator[PseudonymStore]:
    pseudonym_store = PseudonymStore(os.path.join(str(tmp_path), "test_pseudonym.db"))
    yield pseudonym_store
    pseudonym_store.close()


def _typed(number: str, *, size: int = 4, sep: str = " ") -> str:
    return sep.join(number[i : i + size] for i in range(0, len(number), size))


class TestEveryNetworkIsConfidential:
    @pytest.mark.parametrize("number", _CARDS.values(), ids=_CARDS.keys())
    def test_a_card_number_is_confidential(self, number: str) -> None:
        result = classify_content(f"my card is {number} thanks", _ENABLED)

        assert result.level == SensitivityLevel.S3
        assert result.patterns == ["bank_card"]

    @pytest.mark.parametrize("number", _OUT_OF_RANGE.values(), ids=_OUT_OF_RANGE.keys())
    def test_a_valid_looking_number_outside_every_network_is_not(self, number: str) -> None:
        assert classify_content(f"my number is {number} thanks", _ENABLED).level != SensitivityLevel.S3

    @pytest.mark.parametrize("number", ["2223003122003223", "378282246310006", "3566002020360506"])
    def test_a_number_that_fails_the_luhn_check_is_not(self, number: str) -> None:
        assert classify_content(f"my number is {number} thanks", _ENABLED).level != SensitivityLevel.S3

    @pytest.mark.parametrize("number", ["5555555555554444", "2223003122003222", "3566002020360505", "6011111111111117"])
    def test_sixteen_digits_typed_in_fours_are_confidential(self, number: str) -> None:
        for sep in (" ", "-"):
            result = classify_content(f"card {_typed(number, sep=sep)} ok", _ENABLED)
            assert result.level == SensitivityLevel.S3
            assert result.patterns == ["bank_card"]

    def test_the_typed_form_of_an_amex_is_four_six_five(self) -> None:
        for text in ("card 3782 822463 10005 ok", "card 3782-822463-10005 ok"):
            result = classify_content(text, _ENABLED)
            assert result.level == SensitivityLevel.S3
            assert result.patterns == ["bank_card"]

    @pytest.mark.parametrize(
        "text", ["card 3782 8224 6310 005 ok", "card 3782 822463-10005 ok"], ids=["4-4-4-3", "mixed"]
    )
    def test_an_amex_typed_in_any_other_way_is_not_taken_for_a_card(self, text: str) -> None:
        assert classify_content(text, _ENABLED).level != SensitivityLevel.S3


class TestExpiryAndCvvAfterTheNumber:
    """A card is usually typed with its expiry date; those digits are not part of the number."""

    @pytest.mark.parametrize(
        "text",
        [
            "card 4532 0151 1283 0366 12/28",
            "card 4532-0151-1283-0366 12/28",
            "card 4532 0151 1283 0366 1228",
            "card 6200 0000 0000 0005 12/28",
        ],
        ids=["spaced", "hyphenated", "four-digit-expiry", "unionpay-16"],
    )
    def test_the_card_is_confidential(self, text: str) -> None:
        result = classify_content(text, _ENABLED)

        assert result.level == SensitivityLevel.S3
        assert result.patterns == ["bank_card"]

    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            (
                "card 4532 0151 1283 0366 12/28",
                "card **** **** **** 0366 [PII:bank_card] 12/28",
            ),
            (
                "card 6200 0000 0000 0005 12/28",
                "card **** **** **** 0005 [PII:bank_card] 12/28",
            ),
        ],
        ids=["visa", "unionpay-16"],
    )
    def test_only_the_number_is_masked(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)

    def test_only_the_number_is_replaced_and_restored(self, store: PseudonymStore) -> None:
        text = "Card: 4532 0151 1283 0366 12/28"

        result = pseudonymize_text(text, store, SensitivityLevel.S3)

        assert result.text == "Card: <BANK_CARD_1> 12/28"
        assert store.resolve_all(result.text) == text


class TestRedactingRedactedText:
    @pytest.mark.parametrize(
        "text",
        [
            "card 2223003122003222 ok",
            "card 3782 822463 10005 ok",
            "card 3566 0020 2036 0505 12/28 ok",
            "card 6011111111111117, cvv 123",
        ],
    )
    def test_a_second_pass_changes_nothing(self, text: str) -> None:
        once, _ = redact_pii(text)

        twice, count = redact_pii(once)

        assert twice == once
        assert count == 0


class TestRedactedAndRestored:
    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            ("card 2223003122003222 ok", "card **** **** **** 3222 [PII:bank_card] ok"),
            ("card 378282246310005 ok", "card **** **** **** 0005 [PII:bank_card] ok"),
            ("card 3782 822463 10005 ok", "card **** **** **** 0005 [PII:bank_card] ok"),
            ("card 3566 0020 2036 0505 ok", "card **** **** **** 0505 [PII:bank_card] ok"),
            ("card 6011111111111117 ok", "card **** **** **** 1117 [PII:bank_card] ok"),
        ],
        ids=["mastercard-2-series", "amex", "amex-typed", "jcb-typed", "discover"],
    )
    def test_a_card_is_masked_to_its_last_four_digits(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)

    @pytest.mark.parametrize(
        "card",
        ["2223003122003222", "378282246310005", "3782 822463 10005", "3566 0020 2036 0505", "6011111111111117"],
        ids=["mastercard-2-series", "amex", "amex-typed", "jcb-typed", "discover"],
    )
    def test_a_card_is_replaced_and_restored_as_typed(self, store: PseudonymStore, card: str) -> None:
        result = pseudonymize_text(f"Card: {card}, thanks", store, SensitivityLevel.S3)

        assert result.text == "Card: <BANK_CARD_1>, thanks"
        assert store.resolve_all(result.text) == f"Card: {card}, thanks"
