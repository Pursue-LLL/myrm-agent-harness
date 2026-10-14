"""The checksums behind the built-in PII patterns, and the one rule that says which match is a real hit."""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.core.security.detection.pii_patterns import (
    EMAIL_RE,
    S2_PATTERNS,
    S3_PATTERNS,
    bank_card_valid,
    china_id_valid,
    is_confirmed,
    luhn_valid,
)


class TestChinaIdValidation:
    def test_valid_id(self) -> None:
        assert china_id_valid("110101199003074530") is True

    def test_invalid_checksum(self) -> None:
        assert china_id_valid("110101199003074531") is False

    def test_short_id(self) -> None:
        assert china_id_valid("1234567") is False

    def test_digits_that_are_not_decimal_fail_instead_of_raising(self) -> None:
        assert china_id_valid("²" * 17 + "X") is False


class TestLuhnValidation:
    def test_valid_card(self) -> None:
        assert luhn_valid("4532015112830366") is True

    def test_invalid_card(self) -> None:
        assert luhn_valid("4532015112830367") is False

    def test_too_short(self) -> None:
        assert luhn_valid("12345") is False

    def test_non_digit(self) -> None:
        assert luhn_valid("abc") is False

    def test_digits_that_are_not_decimal_fail_instead_of_raising(self) -> None:
        assert luhn_valid("²" * 16) is False

    def test_a_bank_card_is_checked_without_its_separators(self) -> None:
        assert bank_card_valid("4532 0151 1283 0366") is True
        assert bank_card_valid("4532-0151-1283-0366") is True
        assert bank_card_valid("4532 0151 1283 0367") is False


_PATTERNS = dict(S3_PATTERNS) | dict(S2_PATTERNS)


def _confirmed(name: str, text: str) -> bool:
    """Whether the first match of the table pattern *name* in *text* is a real hit."""
    match = _PATTERNS[name].search(text)
    assert match is not None
    return is_confirmed(name, match)


class TestIsConfirmed:
    """The one place that decides which pattern match is a real hit."""

    def test_an_id_card_and_a_bank_card_need_their_checksum(self) -> None:
        assert _confirmed("china_id_card", "110101199003074530") is True
        assert _confirmed("china_id_card", "110101199003074531") is False
        assert _confirmed("bank_card", "4532015112830366") is True
        assert _confirmed("bank_card", "4532015112830367") is False

    def test_an_iban_needs_its_checksum(self) -> None:
        assert _confirmed("iban", "DE89 3704 0044 0532 0130 00") is True
        assert _confirmed("iban", "DE89 3704 0044 0532 0130 01") is False

    def test_a_card_number_inside_an_iban_is_not_a_card(self) -> None:
        assert _confirmed("bank_card", "card 5156 6979 6156 7959") is True
        assert _confirmed("bank_card", "DE79 5156 6979 6156 7959 65") is False

    def test_a_pattern_without_a_checksum_always_survives(self) -> None:
        assert _confirmed("china_phone", "13800138000") is True
        assert _confirmed("email", "a@b.com") is True

    def test_the_names_it_checks_are_the_names_of_the_tables(self) -> None:
        """A renamed table entry would silently skip its checksum."""
        assert {"china_id_card", "bank_card", "iban"} <= set(_PATTERNS)


class TestEmailPattern:
    @pytest.mark.parametrize(
        ("text", "found"),
        [
            ("write to john.doe+tag@mail.example.co.uk today", ["john.doe+tag@mail.example.co.uk"]),
            ("a@b.com,c@d.com", ["a@b.com", "c@d.com"]),
            ("john@acme.com-jane@acme.org.txt", ["john@acme.com", "-jane@acme.org.txt"]),
            ("a@b.com_c@d.com", ["a@b.com", "_c@d.com"]),
            ("x" * 64 + "@x.com", ["x" * 64 + "@x.com"]),
            ("no address here: user@host", []),
        ],
    )
    def test_the_addresses_it_finds(self, text: str, found: list[str]) -> None:
        assert [match.group() for match in EMAIL_RE.finditer(text)] == found

    @pytest.mark.parametrize("run", ["AB12CD34EF56", "a.", "a-", "7", "a@"])
    def test_a_long_run_of_address_characters_is_searched_in_linear_time(self, run: str) -> None:
        # Unbounded, the search rescanned the whole run from every start: 40,000 characters took over a second.
        text = run * (200_000 // len(run))

        started = time.perf_counter()
        list(EMAIL_RE.finditer(text))

        assert time.perf_counter() - started < 3
