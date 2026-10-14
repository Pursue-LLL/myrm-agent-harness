"""US phone numbers as people write them without the country code: "(415) 555-2671", "415-555-2671".

The classifier, the redactor and the pseudonymizer share one pattern table, so each case below is checked at all three:
what a message is classified as, what the model is shown, and what comes back after the reply is restored. A number
written with ``+1`` is an international number and is read by that rule alone, never twice.
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

_WRITTEN = [
    "(415) 555-2671",
    "(415)555-2671",
    "(415) 555 2671",
    "415-555-2671",
    "415.555.2671",
    "415 555 2671",
    "1-415-555-2671",
]


@pytest.fixture()
def store(tmp_path: object) -> Generator[PseudonymStore]:
    pseudonym_store = PseudonymStore(os.path.join(str(tmp_path), "test_pseudonym.db"))
    yield pseudonym_store
    pseudonym_store.close()


class TestClassified:
    @pytest.mark.parametrize("number", _WRITTEN)
    def test_a_us_phone_number_is_sensitive(self, number: str) -> None:
        result = classify_content(f"call me on {number} tonight", _ENABLED)

        assert result.level == SensitivityLevel.S2
        assert result.patterns == ["us_phone"]

    @pytest.mark.parametrize("number", _WRITTEN)
    def test_it_is_sensitive_when_it_is_the_whole_message(self, number: str) -> None:
        assert classify_content(number, _ENABLED).level == SensitivityLevel.S2

    @pytest.mark.parametrize(
        "text",
        [
            "tel +1 415 555 2671 ok",
            "tel +1 (415) 555-2671 ok",
            "tel +1-415-555-2671 ok",
            "tel +1.415.555.2671 ok",
            "tel +7 495 123 4567 ok",
            "tel +358 405 123 4567 ok",
        ],
    )
    def test_a_number_with_the_country_code_is_an_international_number(self, text: str) -> None:
        assert classify_content(text, _ENABLED).patterns == ["intl_phone"]

    @pytest.mark.parametrize(
        "text",
        [
            "build A415-555-2671 done",
            "build 9415-555-2671 done",
            "ref 415-555-2671-9 done",
            "ref 415-555-26719 done",
            "area 115-555-2671 invalid",
            "area 415-155-2671 invalid",
            "area 015-555-2671 invalid",
            "version 4.15.555.2671 pinned",
            "ssn 123-45-6789 ok",
            "date 2026-10-14 ok",
            "pi is 3.14159265358979",
            "host 10.20.30.4 ok",
        ],
        ids=[
            "letter-before",
            "digit-before",
            "digits-after-hyphen",
            "digit-after",
            "area-starts-with-1",
            "exchange-starts-with-1",
            "area-starts-with-0",
            "dotted-version",
            "ssn",
            "date",
            "pi",
            "ip",
        ],
    )
    def test_digits_that_only_look_like_a_phone_number_are_not_one(self, text: str) -> None:
        assert "us_phone" not in classify_content(text, _ENABLED).patterns


class TestRedacted:
    @pytest.mark.parametrize("number", _WRITTEN)
    def test_a_us_phone_number_is_masked_to_its_last_four_digits(self, number: str) -> None:
        assert redact_pii(f"call {number} now") == ("call ***-***-2671 [PII:phone] now", 1)

    @pytest.mark.parametrize("text", ["tel +1 415 555 2671 ok", "tel +1 (415) 555-2671 ok", "tel +7 495 123 4567 ok"])
    def test_a_number_with_the_country_code_is_masked_once(self, text: str) -> None:
        masked, count = redact_pii(text)

        assert count == 1
        assert masked.count("[PII:phone]") == 1

    @pytest.mark.parametrize("number", _WRITTEN)
    def test_a_second_pass_changes_nothing(self, number: str) -> None:
        once, _ = redact_pii(f"call {number} now")

        twice, count = redact_pii(once)

        assert twice == once
        assert count == 0

    def test_a_number_is_left_alone_when_only_confidential_content_is_redacted(self) -> None:
        text = "call (415) 555-2671, card 4532015112830366"

        masked, count = redact_pii(text, levels=frozenset({SensitivityLevel.S3}))

        assert masked == "call (415) 555-2671, card **** **** **** 0366 [PII:bank_card]"
        assert count == 1


class TestPseudonymized:
    @pytest.mark.parametrize("number", _WRITTEN)
    def test_a_us_phone_number_is_replaced_and_restored_as_typed(self, store: PseudonymStore, number: str) -> None:
        result = pseudonymize_text(f"Call {number}, thanks", store, SensitivityLevel.S2)

        assert result.text == "Call <PHONE_NUMBER_1>, thanks"
        assert store.resolve_all(result.text) == f"Call {number}, thanks"

    @pytest.mark.parametrize("number", ["+1 (415) 555-2671", "+1 415 555 2671", "+7 495 123 4567"])
    def test_a_number_with_the_country_code_is_replaced_once(self, store: PseudonymStore, number: str) -> None:
        result = pseudonymize_text(f"Call {number}, thanks", store, SensitivityLevel.S2)

        assert result.text == "Call <PHONE_NUMBER_1>, thanks"
        assert result.count == 1
        assert store.resolve_all(result.text) == f"Call {number}, thanks"
