"""IBAN detector — international bank account numbers, confirmed by country length and the mod-97 check.

An IBAN is two letters of country, two check digits and a country-specific account part, written in one run or in
groups of four (``DE89 3704 0044 0532 0130 00``). The pattern is built from the length every country uses, so a match
ends exactly where its IBAN does and a word that follows (``... 3201 und``) is never swallowed; the mod-97 check then
confirms it (one in 97 random look-alikes survives it, and only with a valid country code and the exact length).

[INPUT]
- (none: standard library only)

[OUTPUT]
- IBAN_LENGTHS: total length of an IBAN per ISO 3166 country code
- IBAN_RE: pattern of every IBAN-shaped token (a match still needs iban_valid)
- iban_valid(): whether a match is an IBAN: known country, exact length, mod-97 remainder 1
- inside_iban(): whether a span of a text lies within a valid IBAN

[POS]
IBAN detection for the PII pattern tables. The lengths are those of the SWIFT IBAN registry (89 countries). Typed
with hyphens or other separators, an IBAN is not matched.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping

IBAN_LENGTHS: Mapping[str, int] = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BI": 27,
    "BR": 29, "BY": 28, "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DJ": 27, "DK": 18, "DO": 28,
    "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FK": 18, "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23,
    "GL": 18, "GR": 27, "GT": 28, "HN": 28, "HR": 21, "HU": 28, "IE": 22, "IL": 23, "IQ": 23, "IS": 26,
    "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "LY": 25, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MN": 20, "MR": 27, "MT": 31, "MU": 30, "NI": 28,
    "NL": 18, "NO": 15, "OM": 23, "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22,
    "RU": 33, "SA": 24, "SC": 31, "SD": 18, "SE": 24, "SI": 19, "SK": 24, "SM": 27, "SO": 23, "ST": 25,
    "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20, "YE": 30,
}  # fmt: skip

_GROUP = 4
# The longest way to print an IBAN: every character plus one space per group.
_MAX_PRINTED_LENGTH = max(IBAN_LENGTHS.values()) + max(IBAN_LENGTHS.values()) // _GROUP


def _length_branch(length: int, countries: list[str]) -> str:
    """The pattern of the IBANs of *length* characters, one run or in groups of four with a short last group."""
    groups, last = divmod(length - 4, _GROUP)
    tail = rf"(?: ?[A-Z0-9]{{{last}}})" if last else ""
    return rf"(?:{'|'.join(sorted(countries))})\d{{2}}(?: ?[A-Z0-9]{{{_GROUP}}}){{{groups}}}{tail}"


def _build_iban_re() -> re.Pattern[str]:
    countries_by_length: defaultdict[int, list[str]] = defaultdict(list)
    for country, length in IBAN_LENGTHS.items():
        countries_by_length[length].append(country)
    branches = "|".join(_length_branch(length, countries) for length, countries in sorted(countries_by_length.items()))
    # The lookahead rejects most positions of a text with one cheap check, before any alternative is tried.
    return re.compile(rf"(?<![A-Za-z0-9])(?=[A-Za-z]{{2}}\d{{2}})(?:{branches})(?![A-Za-z0-9])", re.IGNORECASE)


IBAN_RE = _build_iban_re()


def iban_valid(value: str) -> bool:
    """Whether *value* (typed with or without the spaces between groups) is an IBAN: known country, exact length, mod 97."""
    compact = value.replace(" ", "").upper()
    if not (compact.isascii() and compact.isalnum()) or IBAN_LENGTHS.get(compact[:2]) != len(compact):
        return False
    if not compact[2:4].isdecimal():
        return False
    # Move the country and check digits to the end and read the letters as numbers (A=10 ... Z=35).
    rearranged = compact[4:] + compact[:4]
    return int("".join(str(int(char, 36)) for char in rearranged)) % 97 == 1


def inside_iban(text: str, start: int, end: int) -> bool:
    """Whether ``text[start:end]`` lies within a valid IBAN of *text*.

    Looks only at the stretch before *start* in which an IBAN that reaches *end* could begin, so the cost does not
    grow with the length of the text.
    """
    for first in range(max(0, start - _MAX_PRINTED_LENGTH), start):
        match = IBAN_RE.match(text, first)
        if match and match.end() >= end and iban_valid(match.group(0)):
            return True
    return False
