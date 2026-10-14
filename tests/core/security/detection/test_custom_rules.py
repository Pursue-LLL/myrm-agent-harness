"""custom_rules: where a user-defined keyword or pattern sits in a text.

One span finder serves classification, redaction and pseudonymization, so a term that is detected is a term that is
masked. The cases below are the ones a keyword list meets in real conversations: Chinese terms inside a sentence,
ASCII terms inside Chinese text, repeated occurrences, and text an earlier redaction already rewrote.
"""

from __future__ import annotations

import re
import time

import pytest

from myrm_agent_harness.core.security.detection import custom_rules as custom_rules_module
from myrm_agent_harness.core.security.detection.custom_rules import (
    NO_CUSTOM_RULES,
    CustomRules,
    custom_rules,
    find_custom_spans,
    first_custom_span,
    ineffective_patterns,
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


_EXTREME_PATTERNS = ["([", "a{99999999999}", "(" * 5000 + "a" + ")" * 5000]

# Patterns written in the standard-library syntax match exactly what ``re`` matches.
_STANDARD_SYNTAX_CASES = [
    (r"EMP-\d{6}", "EMP-123456, emp-654321 and EMP-12"),
    (r"1[3-9]\d{9}", "call 13812345678 or 19900001111, not 12345678901"),
    (r"\d{17}[\dXx]", "id 11010519491231002X and 110105194912310021"),
    (r"[\w.+-]+@acme\.com", "mail Bob.Smith+x@ACME.com, bob@acme.org"),
    (r"\bproject-(?:alpha|beta)\b", "Project-Alpha, project-betamax, PROJECT-BETA"),
    (r"(?<=token=)[^&\s]+", "?token=abc123&x=1 token=zzz"),
    (r"(\w)\1{2,}", "aaa bbb abab ZZZZ"),
    (r"^\s*secret:.*$", "  secret: hunter2"),
    (r"(?i)caf\u00e9|na\u00efve", "CAF\u00c9 and Na\u00cfVE"),
    (r"\u5e26\u5934.{0,3}\u8d1f\u8d23\u4eba", "\u5e26\u5934\u4eba\u662f\u8d1f\u8d23\u4eba\u5f20\u4e09"),
    (r"a.*?b", "a1b a2b\nab"),
    (r"x*", "xxabxx"),
]


class TestPatternEngine:
    """Patterns are what users paste from an AI assistant: Unicode properties and named groups must work."""

    def test_a_unicode_property_pattern_matches_chinese_text(self) -> None:
        rules = CustomRules(patterns=(r"\p{Han}{2,4}科技",))
        assert _hits("客户：星河科技已确认", rules) == ["星河科技"]

    def test_a_named_group_pattern_matches(self) -> None:
        rules = CustomRules(patterns=(r"(?<code>[A-Z]{3})-\d{4}",))
        assert _hits("ref ACM-2048 and ZZZ-0001", rules) == ["ACM-2048", "ZZZ-0001"]

    def test_an_inline_flag_pattern_matches(self) -> None:
        assert _hits("see Acme-204815", CustomRules(patterns=(r"(?i)acme-\d+",))) == ["Acme-204815"]

    @pytest.mark.parametrize(("pattern", "text"), _STANDARD_SYNTAX_CASES)
    def test_a_standard_syntax_pattern_matches_where_the_re_module_matches(self, pattern: str, text: str) -> None:
        expected = [match.span() for match in re.finditer(pattern, text, re.IGNORECASE) if match.end() > match.start()]
        found = find_custom_spans(text, CustomRules(patterns=(pattern,)))
        assert [(span.start, span.end) for span in found] == expected

    @pytest.mark.parametrize("pattern", _EXTREME_PATTERNS)
    def test_an_uncompilable_pattern_never_matches_and_never_crashes_a_turn(self, pattern: str) -> None:
        assert find_custom_spans("aaa", CustomRules(patterns=(pattern,))) == []
        assert first_custom_span("aaa", CustomRules(patterns=(pattern,))) is None

    def test_ineffective_patterns_names_the_ones_that_cannot_match(self) -> None:
        patterns = ("([", r"EMP-\d{6}", r"\p{Han}+", "a{99999999999}", "([")
        assert ineffective_patterns(patterns) == ("([", "a{99999999999}")

    def test_no_ineffective_patterns_in_a_sound_rule_list(self) -> None:
        assert ineffective_patterns((r"EMP-\d{6}", r"(?<n>x)y")) == ()
        assert ineffective_patterns(()) == ()


class TestPatternTimeout:
    """A pattern that backtracks without end must not stall the instance: the text then counts as its hit."""

    _STUCK_TEXT = "a" * 60 + "!"
    _STUCK_PATTERN = r"(a|aa)+$"

    @pytest.fixture(autouse=True)
    def _short_budget(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(custom_rules_module, "_PATTERN_TIMEOUT_SECONDS", 0.05)

    def test_a_pattern_that_cannot_finish_covers_the_whole_text(self) -> None:
        rules = CustomRules(patterns=(self._STUCK_PATTERN,))

        started = time.perf_counter()
        spans = find_custom_spans(self._STUCK_TEXT, rules)

        assert time.perf_counter() - started < 5
        assert [(span.start, span.end, span.timed_out) for span in spans] == [(0, len(self._STUCK_TEXT), True)]

    def test_the_whole_text_hit_does_not_yield_to_markers_already_in_the_text(self) -> None:
        text = f"[PII:phone] {self._STUCK_TEXT}"
        spans = find_custom_spans(text, CustomRules(patterns=(self._STUCK_PATTERN,)))
        assert [(span.start, span.end) for span in spans] == [(0, len(text))]

    def test_the_first_span_reports_the_timeout(self) -> None:
        span = first_custom_span(self._STUCK_TEXT, CustomRules(patterns=(self._STUCK_PATTERN,)))
        assert span is not None
        assert (span.kind, span.rule, span.timed_out) == ("pattern", self._STUCK_PATTERN, True)

    def test_rules_after_the_timed_out_pattern_add_nothing(self) -> None:
        rules = CustomRules(keywords=("aaa",), patterns=(self._STUCK_PATTERN, r"a+"))
        assert [(span.start, span.end) for span in find_custom_spans(self._STUCK_TEXT, rules)] == [
            (0, len(self._STUCK_TEXT))
        ]

    def test_a_pattern_that_finishes_in_time_is_a_plain_match(self) -> None:
        spans = find_custom_spans("EMP-123456", CustomRules(patterns=(r"EMP-\d{6}",)))
        assert [(span.start, span.end, span.timed_out) for span in spans] == [(0, 10, False)]


_TOO_LARGE_TO_BUILD = {
    "nested_exact": r"(?:a{1000}){1000}",
    "nested_minimum": r"(?:a{1000,}){1000,}",
    "nested_class": r"((a|b){1000}){1000}",
    "three_levels": r"(?:(?:a{100}){100}){100}",
    "single_exact": r"a{10000000}",
    "single_class": r"\d{99999999}",
    "past_the_budget": r"a{10002}",
}


class TestPatternSize:
    """The ``regex`` engine lays every copy of a counted repeat out when it compiles (``a{10000000}`` takes 2.7 GB where
    ``re`` stores the count), so a short pattern could exhaust the memory of the whole server."""

    @pytest.mark.parametrize("pattern", _TOO_LARGE_TO_BUILD.values(), ids=_TOO_LARGE_TO_BUILD.keys())
    def test_a_pattern_too_large_to_build_is_ineffective(self, pattern: str) -> None:
        started = time.perf_counter()
        assert ineffective_patterns((pattern,)) == (pattern,)
        assert find_custom_spans("aaa 123", CustomRules(patterns=(pattern,))) == []
        assert time.perf_counter() - started < 1

    @pytest.mark.parametrize(
        "pattern",
        [
            r"a{10001}",
            "|".join(f"customer{number}" for number in range(5000)),
            r"\d{17}[\dXx]",
            r"[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}([A-Z0-9]?){0,16}",
            r"(?:\d{3}-){3}\d{4}",
            r"(?:\w+\s){50}",
            r"\d{1,100000}",
            r"[\s\S]{0,5000}",
            r"\p{Han}{2,4}科技",
            r"(?<code>[A-Z]{3})-\d{4}",
            r"\[\d{4}\]\d{4}",
            r"\{99999999\}",
            r"[{99999999}]{3}",
        ],
    )
    def test_a_realistic_counted_pattern_is_kept(self, pattern: str) -> None:
        assert ineffective_patterns((pattern,)) == ()


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
