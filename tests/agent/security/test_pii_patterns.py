"""The checksums behind the built-in PII patterns, and the one rule that says which match survives its checksum."""

from __future__ import annotations

from myrm_agent_harness.core.security.detection.pii_patterns import (
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


class TestIsConfirmed:
    """The one place that decides which pattern match survives its checksum."""

    def test_an_id_card_and_a_bank_card_need_their_checksum(self) -> None:
        assert is_confirmed("china_id_card", "110101199003074530") is True
        assert is_confirmed("china_id_card", "110101199003074531") is False
        assert is_confirmed("bank_card", "4532015112830366") is True
        assert is_confirmed("bank_card", "4532015112830367") is False

    def test_a_pattern_without_a_checksum_always_survives(self) -> None:
        assert is_confirmed("china_phone", "13800138000") is True
        assert is_confirmed("email", "a@b.com") is True
