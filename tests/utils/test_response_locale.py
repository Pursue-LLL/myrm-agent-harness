"""Tests for response_locale policy suffix builder."""

from myrm_agent_harness.utils.response_locale import (
    build_response_locale_suffix,
    parse_response_locale_policy,
)


def test_parse_missing_policy() -> None:
    assert parse_response_locale_policy(None) is None
    assert parse_response_locale_policy({}) is None


def test_parse_ko_formal_policy() -> None:
    policy = parse_response_locale_policy({"response_locale_policy": {"locale": "ko-KR", "formality": "formal-polite"}})
    assert policy is not None
    assert policy["locale"] == "ko-KR"
    assert policy["formality"] == "formal-polite"


def test_build_ko_formal_suffix() -> None:
    suffix = build_response_locale_suffix({"response_locale_policy": {"locale": "ko-KR", "formality": "formal-polite"}})
    assert "합니다" in suffix
    assert "Korean" in suffix


def test_build_ko_casual_suffix() -> None:
    suffix = build_response_locale_suffix({"response_locale_policy": {"locale": "ko", "formality": "casual"}})
    assert "conversational" in suffix
    assert "합니다" not in suffix


def test_non_ko_locale_returns_empty() -> None:
    assert (
        build_response_locale_suffix({"response_locale_policy": {"locale": "ja-JP", "formality": "formal-polite"}})
        == ""
    )
