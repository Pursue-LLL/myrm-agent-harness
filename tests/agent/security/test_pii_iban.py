"""IBANs as people write them, one in a run or in groups of four.

The classifier, the redactor and the pseudonymizer share one pattern table, so each case is checked at the layers that
read it: the level a message is given, what the model is shown, and what comes back after the reply is restored.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Generator

import pytest

from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii
from myrm_agent_harness.core.security.detection.iban import IBAN_LENGTHS, IBAN_RE, iban_valid, inside_iban
from myrm_agent_harness.core.security.detection.pii_classifier import classify_content
from myrm_agent_harness.core.security.detection.pseudonym_store import PseudonymStore
from myrm_agent_harness.core.security.detection.pseudonymizer import pseudonymize_text
from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

_ENABLED = PrivacyPolicy(enabled=True)

# The registry's example IBANs, one per length class that countries commonly use.
_PUBLISHED = [
    "DE89 3704 0044 0532 0130 00",
    "GB82 WEST 1234 5698 7654 32",
    "FR14 2004 1010 0505 0001 3M02 606",
    "NL91 ABNA 0417 1643 00",
    "ES91 2100 0418 4502 0005 1332",
    "IT60 X054 2811 1010 0000 0123 456",
    "CH93 0076 2011 6238 5295 7",
    "BE68 5390 0754 7034",
    "NO93 8601 1117 947",
    "AT61 1904 3002 3457 3201",
    "PL61 1090 1014 0000 0712 1981 2874",
    "RU02 0445 2560 0407 0281 0412 3456 7890 1",
    "MT84 MALT 0110 0001 2345 MTLC AST0 01S",
    "BR18 0036 0305 0000 1000 9795 493C 1",
]

# Valid IBANs whose digits also pass the Luhn check of a card network: the digit run is a card number to the card
# pattern, an account number to the person who typed it.
_LOOKS_LIKE_A_CARD = ["DE79 5156 6979 6156 7959 65", "AT480642482960179677"]


@pytest.fixture()
def store(tmp_path: object) -> Generator[PseudonymStore]:
    pseudonym_store = PseudonymStore(os.path.join(str(tmp_path), "test_pseudonym.db"))
    yield pseudonym_store
    pseudonym_store.close()


def _compact(iban: str) -> str:
    return iban.replace(" ", "")


def _grouped(iban: str) -> str:
    compact = _compact(iban)
    return " ".join(compact[i : i + 4] for i in range(0, len(compact), 4))


def _build(country: str) -> str:
    """A valid IBAN of *country* with a digit-only account part, check digits computed independently of the module."""
    account = ("1234567890" * 4)[: IBAN_LENGTHS[country] - 4]
    remainder = int("".join(str(int(char, 36)) for char in account + country + "00")) % 97
    return f"{country}{98 - remainder:02d}{account}"


def _ibans_in(text: str) -> list[str]:
    return [m.group(0) for m in IBAN_RE.finditer(text) if iban_valid(m.group(0))]


class TestIbanDetection:
    @pytest.mark.parametrize("iban", _PUBLISHED)
    def test_a_published_iban_is_valid_in_both_forms(self, iban: str) -> None:
        assert iban_valid(iban) is True
        assert iban_valid(_compact(iban)) is True

    @pytest.mark.parametrize("iban", _PUBLISHED)
    @pytest.mark.parametrize("form", [_compact, _grouped], ids=["contiguous", "grouped"])
    def test_an_iban_is_sensitive(self, iban: str, form: Callable[[str], str]) -> None:
        result = classify_content(f"Please pay to {form(iban)} today", _ENABLED)

        assert result.level == SensitivityLevel.S2
        assert result.patterns == ["iban"]

    @pytest.mark.parametrize("country", sorted(IBAN_LENGTHS))
    def test_every_country_is_matched_whole_in_both_forms(self, country: str) -> None:
        iban = _build(country)

        assert iban_valid(iban) is True
        assert _ibans_in(f"to {iban}.") == [iban]
        assert _ibans_in(f"to {_grouped(iban)}.") == [_grouped(iban)]

    def test_a_lowercase_iban_is_matched(self) -> None:
        assert _ibans_in("iban de89 3704 0044 0532 0130 00") == ["de89 3704 0044 0532 0130 00"]

    @pytest.mark.parametrize(
        ("text", "iban"),
        [
            ("AT61 1904 3002 3457 3201 und danke", "AT61 1904 3002 3457 3201"),
            ("ES91 2100 0418 4502 0005 1332 and more", "ES91 2100 0418 4502 0005 1332"),
            ("BE68 5390 0754 7034 to Anna", "BE68 5390 0754 7034"),
            ("DE89 3704 0044 0532 0130 00 und 0000", "DE89 3704 0044 0532 0130 00"),
        ],
        ids=["german-word", "english-word", "length-multiple-of-four", "trailing-digits"],
    )
    def test_the_word_after_an_iban_is_not_part_of_it(self, text: str, iban: str) -> None:
        assert _ibans_in(text) == [iban]

    @pytest.mark.parametrize(
        "text",
        [
            "DE89370400440532013001",
            "DE8937040044053201300",
            "DE893704004405320130000",
            "XX89370400440532013000",
            "xDE89370400440532013000",
            "DE89370400440532013000x",
            "DE89-3704-0044-0532-0130-00",
            "DE89  3704 0044 0532 0130 00",
            "123e4567-e89b-12d3-a456-426614174000",
            "da39a3ee5e6b4b0d3255bfef95601890afd80709",
        ],
        ids=[
            "bad-check-digits",
            "one-short",
            "one-long",
            "unknown-country",
            "glued-to-a-letter",
            "glued-to-a-letter-after",
            "hyphens",
            "double-space",
            "uuid",
            "sha1",
        ],
    )
    def test_what_only_looks_like_an_iban_is_not_one(self, text: str) -> None:
        assert _ibans_in(text) == []
        assert classify_content(text, _ENABLED).patterns != ["iban"]

    def test_a_disabled_policy_holds_nothing(self) -> None:
        assert classify_content("pay DE89370400440532013000", PrivacyPolicy()).level == SensitivityLevel.S1


class TestIbanMasking:
    @pytest.mark.parametrize(
        ("original", "masked"),
        [
            ("pay DE89 3704 0044 0532 0130 00 now", "pay DE** **** **** 3000 [PII:iban] now"),
            ("pay DE89370400440532013000.", "pay DE** **** **** 3000 [PII:iban]."),
            ("pay gb82 west 1234 5698 7654 32 now", "pay GB** **** **** 5432 [PII:iban] now"),
            ("AT61 1904 3002 3457 3201 und danke", "AT** **** **** 3201 [PII:iban] und danke"),
            ("FR14 2004 1010 0505 0001 3M02 606", "FR** **** **** 2606 [PII:iban]"),
        ],
        ids=["grouped", "contiguous", "lowercase", "word-after", "letters-in-account"],
    )
    def test_an_iban_keeps_its_country_and_last_four_characters(self, original: str, masked: str) -> None:
        assert redact_pii(original) == (masked, 1)

    def test_an_iban_typed_in_groups_is_one_redaction_not_a_card(self) -> None:
        _, count = redact_pii("pay DE89 3704 0044 0532 0130 00 now")

        assert count == 1

    def test_a_masked_iban_is_not_masked_again(self) -> None:
        once, _ = redact_pii("pay DE89 3704 0044 0532 0130 00 now")

        assert redact_pii(once) == (once, 0)

    def test_a_number_that_fails_the_checksum_stays(self) -> None:
        assert redact_pii("ref DE89370400440532013001") == ("ref DE89370400440532013001", 0)

    def test_each_level_masks_only_its_own_content(self) -> None:
        text = "pay DE89 3704 0044 0532 0130 00 now"

        assert redact_pii(text, levels=frozenset({SensitivityLevel.S3})) == (text, 0)
        assert redact_pii(text, levels=frozenset({SensitivityLevel.S2}))[1] == 1


class TestCardNumberInsideIban:
    @pytest.mark.parametrize("iban", _LOOKS_LIKE_A_CARD)
    def test_an_iban_that_passes_the_luhn_check_is_sensitive_not_confidential(self, iban: str) -> None:
        result = classify_content(f"pay {iban} now", _ENABLED)

        assert result.level == SensitivityLevel.S2
        assert result.patterns == ["iban"]

    @pytest.mark.parametrize("iban", _LOOKS_LIKE_A_CARD)
    def test_it_is_masked_as_an_iban_and_only_at_its_own_level(self, iban: str) -> None:
        text = f"pay {iban} now"
        masked, count = redact_pii(text)

        assert count == 1
        assert "[PII:iban]" in masked
        assert "bank_card" not in masked
        assert redact_pii(text, levels=frozenset({SensitivityLevel.S3})) == (text, 0)

    @pytest.mark.parametrize("iban", _LOOKS_LIKE_A_CARD)
    def test_it_is_not_pseudonymized_as_a_card(self, store: PseudonymStore, iban: str) -> None:
        text = f"pay {iban} now"

        assert pseudonymize_text(text, store, SensitivityLevel.S3).text == text
        assert pseudonymize_text(text, store, SensitivityLevel.S2).text == "pay <IBAN_1> now"

    def test_a_real_card_beside_an_iban_is_still_a_card(self) -> None:
        text = "pay DE79 5156 6979 6156 7959 65 with card 4532 0151 1283 0366"

        assert classify_content(text, _ENABLED).level == SensitivityLevel.S3
        assert redact_pii(text) == (
            "pay DE** **** **** 5965 [PII:iban] with card **** **** **** 0366 [PII:bank_card]",
            2,
        )

    def test_a_card_that_merely_precedes_an_iban_is_still_a_card(self) -> None:
        text = "4532 0151 1283 0366 DE89 3704 0044 0532 0130 00"

        assert redact_pii(text) == ("**** **** **** 0366 [PII:bank_card] DE** **** **** 3000 [PII:iban]", 2)


class TestInsideIban:
    _TEXT = "to DE89 3704 0044 0532 0130 00 now"

    def test_a_span_within_the_iban(self) -> None:
        start = self._TEXT.index("3704")

        assert inside_iban(self._TEXT, start, start + 19) is True

    def test_a_span_before_or_after_the_iban(self) -> None:
        assert inside_iban(self._TEXT, 0, 2) is False
        assert inside_iban(self._TEXT, self._TEXT.index("now"), len(self._TEXT)) is False

    def test_a_span_that_reaches_beyond_the_iban(self) -> None:
        start = self._TEXT.index("3704")

        assert inside_iban(self._TEXT, start, len(self._TEXT)) is False

    def test_a_text_without_an_iban_is_not_searched_beyond_the_window(self) -> None:
        text = "x" * 10_000 + " 4532 0151 1283 0366 " + "DE89 3704 0044 0532 0130 00"
        start = text.index("4532")

        assert inside_iban(text, start, start + 19) is False


class TestIbanPseudonym:
    def test_an_iban_is_replaced_once_and_restored_as_typed(self, store: PseudonymStore) -> None:
        iban = "DE89 3704 0044 0532 0130 00"
        result = pseudonymize_text(f"Pay to {iban} now", store, SensitivityLevel.S2)

        assert result.text == "Pay to <IBAN_1> now"
        assert result.count == 1
        assert store.resolve_all(result.text) == f"Pay to {iban} now"

    def test_a_contiguous_iban_is_replaced_and_restored_as_typed(self, store: PseudonymStore) -> None:
        iban = "DE89370400440532013000"
        result = pseudonymize_text(f"IBAN: {iban}.", store, SensitivityLevel.S2)

        assert result.text == "IBAN: <IBAN_1>."
        assert store.resolve_all(result.text) == f"IBAN: {iban}."

    def test_the_same_iban_keeps_its_pseudonym_and_another_gets_its_own(self, store: PseudonymStore) -> None:
        text = "from DE89370400440532013000 to GB82WEST12345698765432 via DE89370400440532013000"
        result = pseudonymize_text(text, store, SensitivityLevel.S2)

        assert result.text == "from <IBAN_1> to <IBAN_2> via <IBAN_1>"
        assert store.resolve_all(result.text) == text

    def test_a_confidential_pass_leaves_it_alone(self, store: PseudonymStore) -> None:
        text = "pay DE89 3704 0044 0532 0130 00 now"

        assert pseudonymize_text(text, store, SensitivityLevel.S3).text == text
