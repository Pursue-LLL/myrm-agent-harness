"""TokenStartPattern behaves exactly like a pattern with a lookbehind in front of it."""

from __future__ import annotations

import random
import re
from collections.abc import Iterable

import pytest

from myrm_agent_harness.core.security.detection.leak_detector import _API_KEY_PATTERNS
from myrm_agent_harness.core.security.detection.token_start import NUMBER_START, TOKEN_START, TokenStartPattern

_SK = re.compile(r"sk-[a-zA-Z0-9_-]{8,}")
_WITH_LOOKBEHIND = {name: re.compile(TOKEN_START + pattern.pattern) for name, pattern in _API_KEY_PATTERNS}

_PIECES = (
    "sk-",
    "task-",
    "risk-",
    "ghp_",
    "AKIA",
    "hf_",
    "xoxb-",
    "SG.",
    "sk_live_",
    "gsk_",
    "aB3dE5fG7h" * 5,
    "management-best-practices-for-remote-teams-in-2025",
    "ABCD3FGH5JKL7NOP",
    "0123456789",
    " ",
    "\n",
    "\\n",
    "\\t",
    "%3D",
    "%20",
    "=",
    ":",
    "/",
    '"',
    "_",
    "-",
    ".",
    "密钥",
    "word",
    "Bearer ",
)


def _texts(count: int) -> list[str]:
    rng = random.Random(20261015)
    return ["".join(rng.choices(_PIECES, k=rng.randint(1, 14))) for _ in range(count)]


def _spans(matches: Iterable[re.Match[str]]) -> list[tuple[int, int]]:
    return [m.span() for m in matches]


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("sk-abcdefgh12", True),
        ("key: sk-abcdefgh12", True),
        ("(sk-abcdefgh12)", True),
        ("密钥sk-abcdefgh12", True),
        ("my_sk-abcdefgh12", True),
        ("line\\nsk-abcdefgh12", True),
        ("a\\r\\nsk-abcdefgh12", True),
        ("a\\tsk-abcdefgh12", True),
        ("token%3Dsk-abcdefgh12", True),
        ("q%20sk-abcdefgh12", True),
        ("task-abcdefgh12", False),
        ("1sk-abcdefgh12", False),
        ("\\xsk-abcdefgh12", False),
        ("%3sk-abcdefgh12", False),
        ("nothing here", False),
    ],
)
def test_a_match_counts_only_where_a_token_starts(text: str, found: bool) -> None:
    assert bool(TokenStartPattern(_SK).search(text)) is found


@pytest.mark.parametrize(
    ("text", "found"),
    [("123456789:key", True), ("bot123456789:key", True), ("1123456789:key", False)],
)
def test_the_number_start_rules_out_only_a_longer_number(text: str, found: bool) -> None:
    assert bool(TokenStartPattern(re.compile(r"\d{9}:key"), NUMBER_START).search(text)) is found


def test_a_match_after_a_rejected_one_inside_the_same_run_is_still_found() -> None:
    """The rejected ``sk-`` of "task-" swallows the run, but the key after the hyphen starts a token."""
    text = "task-notes-sk-abcdefgh12"

    assert TokenStartPattern(_SK).search(text) is not None
    assert TokenStartPattern(_SK).sub(lambda m: "[X]", text) == "task-notes-[X]"


def test_every_vendor_shape_gives_the_same_matches_as_a_lookbehind() -> None:
    texts = _texts(1500)
    matched = rejected = 0
    for name, pattern in _API_KEY_PATTERNS:
        wrapped, reference = TokenStartPattern(pattern), _WITH_LOOKBEHIND[name]
        for text in texts:
            assert _spans(wrapped.finditer(text)) == _spans(reference.finditer(text)), (name, text)
            assert (wrapped.search(text) is None) == (reference.search(text) is None), (name, text)
            assert wrapped.sub(lambda m: "[X]", text) == reference.sub(lambda m: "[X]", text), (name, text)
            matched += reference.search(text) is not None
            rejected += reference.search(text) is None and pattern.search(text) is not None
    assert matched > 100, "the texts hold too few keys to show that the wrapper keeps what it should"
    assert rejected > 50, "the texts hold too few mid-word prefixes to show that the wrapper drops what it should"


def test_no_vendor_shape_matches_the_empty_string() -> None:
    """A wrapper that resumes one character after a match would otherwise report an empty match at every position."""
    assert [name for name, pattern in _API_KEY_PATTERNS if pattern.search("") is not None] == []
