"""custom_rules: where a user-defined keyword or pattern sits in a text.

One span finder serves classification, redaction and pseudonymization, so a term that is detected is a term that is
masked. The cases below are the ones a keyword list meets in real conversations: Chinese terms inside a sentence,
ASCII terms inside Chinese text, repeated occurrences, and text an earlier redaction already rewrote.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.detection.custom_rules import (
    NO_CUSTOM_RULES,
    CustomRules,
    custom_rules,
    find_custom_spans,
    first_custom_span,
)
from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel


def _hits(content: str, rules: CustomRules) -> list[str]:
    return [content[span.start : span.end] for span in find_custom_spans(content, rules)]


def _keywords(*words: str) -> CustomRules:
    return CustomRules(keywords=words)


class TestKeywordBoundaries:
    def test_a_chinese_keyword_matches_inside_a_sentence(self) -> None:
        assert _hits("帮我总结凤凰计划Q3预算超支原因，发给李总", _keywords("凤凰计划")) == ["凤凰计划"]

    def test_a_chinese_keyword_alone_is_a_match(self) -> None:
        assert _hits("凤凰计划", _keywords("凤凰计划")) == ["凤凰计划"]

    def test_an_ascii_keyword_does_not_match_inside_a_longer_word(self) -> None:
        assert _hits("the spinners ran fast", _keywords("pin")) == []
        assert _hits("password123", _keywords("pass")) == []

    def test_an_ascii_keyword_matches_as_a_whole_word(self) -> None:
        assert _hits("my pin is here", _keywords("pin")) == ["pin"]

    def test_an_ascii_keyword_matches_between_chinese_characters(self) -> None:
        assert _hits("我的project计划", _keywords("project")) == ["project"]

    def test_an_underscore_continues_a_word(self) -> None:
        assert _hits("project_alpha", _keywords("project")) == []

    def test_a_file_extension_needs_no_leading_boundary_only_a_closed_tail(self) -> None:
        assert _hits("read config.env file", _keywords(".env")) == [".env"]
        assert _hits("read config.envelope", _keywords(".env")) == []

    def test_a_keyword_matches_in_any_case(self) -> None:
        assert _hits("ProjectX and PROJECTX", _keywords("projectx")) == ["ProjectX", "PROJECTX"]

    def test_every_occurrence_is_found(self) -> None:
        content = "凤凰计划的预算，凤凰计划的人员，以及凤凰计划的排期"
        assert _hits(content, _keywords("凤凰计划")) == ["凤凰计划"] * 3

    def test_the_longer_of_two_overlapping_keywords_wins(self) -> None:
        assert _hits("凤凰计划启动", _keywords("凤凰", "凤凰计划")) == ["凤凰计划"]

    def test_a_keyword_made_of_regex_syntax_is_literal(self) -> None:
        assert _hits("price (a+b)* total", _keywords("(a+b)*")) == ["(a+b)*"]


class TestPatterns:
    def test_a_pattern_matches_every_occurrence(self) -> None:
        rules = CustomRules(patterns=(r"EMP-\d{6}",))
        assert _hits("EMP-123456 reports to EMP-654321", rules) == ["EMP-123456", "EMP-654321"]

    def test_a_pattern_matches_in_any_case(self) -> None:
        assert _hits("see emp-123456", CustomRules(patterns=(r"EMP-\d{6}",))) == ["emp-123456"]

    def test_an_invalid_pattern_never_matches(self) -> None:
        assert _hits("hello world", CustomRules(patterns=("([",))) == []

    def test_a_pattern_that_can_match_nothing_yields_no_empty_span(self) -> None:
        assert find_custom_spans("hello", CustomRules(patterns=("x*",))) == []

    def test_a_keyword_and_a_pattern_on_the_same_text_do_not_overlap(self) -> None:
        rules = CustomRules(keywords=("EMP",), patterns=(r"EMP-\d{6}",))
        assert _hits("EMP-123456", rules) == ["EMP-123456"]


class TestAlreadyRewrittenText:
    @pytest.mark.parametrize(
        "marker",
        ["[PII:phone]", "[REDACTED] [PII:custom]", "[REDACTED:openai_key]", "<PHONE_NUMBER_1>", "<CUSTOM_KEYWORD_2>"],
    )
    def test_a_keyword_inside_an_earlier_marker_is_ignored(self, marker: str) -> None:
        rules = _keywords("phone", "PII", "custom", "REDACTED", "PHONE_NUMBER", "KEYWORD", "openai_key")
        assert find_custom_spans(f"call {marker} now", rules) == []

    def test_a_keyword_next_to_a_marker_still_matches(self) -> None:
        assert _hits("凤凰计划 [PII:phone] 凤凰计划", _keywords("凤凰计划")) == ["凤凰计划", "凤凰计划"]


class TestRulesFromPolicy:
    def test_the_rules_of_a_level_come_from_that_level_only(self) -> None:
        policy = PrivacyPolicy(
            enabled=True,
            custom_keywords_s2=("微信号",),
            custom_keywords_s3=("绝密",),
            custom_patterns_s2=(r"A-\d+",),
            custom_patterns_s3=(r"B-\d+",),
        )
        assert custom_rules(policy, SensitivityLevel.S2) == CustomRules(("微信号",), (r"A-\d+",))
        assert custom_rules(policy, SensitivityLevel.S3) == CustomRules(("绝密",), (r"B-\d+",))

    def test_several_levels_combine(self) -> None:
        policy = PrivacyPolicy(enabled=True, custom_keywords_s2=("微信号",), custom_keywords_s3=("绝密",))
        assert custom_rules(policy, SensitivityLevel.S2, SensitivityLevel.S3).keywords == ("微信号", "绝密")

    def test_s1_has_no_rules(self) -> None:
        policy = PrivacyPolicy(enabled=True, custom_keywords_s3=("绝密",))
        assert custom_rules(policy, SensitivityLevel.S1) == NO_CUSTOM_RULES

    def test_blank_entries_are_dropped_because_an_empty_keyword_would_match_everywhere(self) -> None:
        policy = PrivacyPolicy(enabled=True, custom_keywords_s3=("", "  ", " 绝密 "), custom_patterns_s3=("",))
        assert custom_rules(policy, SensitivityLevel.S3) == CustomRules(("绝密",), ())


class TestFirstSpan:
    def test_no_rules_no_span(self) -> None:
        assert first_custom_span("凤凰计划", NO_CUSTOM_RULES) is None
        assert find_custom_spans("凤凰计划", NO_CUSTOM_RULES) == []

    def test_the_first_span_names_its_rule(self) -> None:
        span = first_custom_span("请提供 社保号码 信息", _keywords("社保号码"))
        assert span is not None
        assert (span.kind, span.rule) == ("keyword", "社保号码")

    def test_a_pattern_span_names_the_pattern(self) -> None:
        span = first_custom_span("PROJ-123456", CustomRules(patterns=(r"PROJ-\d{6}",)))
        assert span is not None
        assert (span.kind, span.rule) == ("pattern", r"PROJ-\d{6}")

    def test_no_hit_is_none(self) -> None:
        assert first_custom_span("nothing here", _keywords("凤凰计划")) is None
