"""Unit tests for query_analyzer module (bilingual query analysis)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.memory.query_analyzer import (
    QueryContext,
    analyze_query,
    contains_person_name,
    contains_quoted_phrase,
    extract_person_names,
    extract_quoted_phrases,
    extract_temporal_markers,
    infer_reference_time,
    is_assistant_reference_query,
    is_preference_query,
)


class TestExtractQuotedPhrases:
    """Test quoted phrase extraction."""

    def test_double_quotes(self) -> None:
        assert extract_quoted_phrases('Find "hello world" please') == ["hello world"]

    def test_single_quotes(self) -> None:
        assert extract_quoted_phrases("Find 'hello world' please") == ["hello world"]

    def test_chinese_quotes(self) -> None:
        assert extract_quoted_phrases("搜索「你好世界」的内容") == ["你好世界"]

    def test_multiple_quotes(self) -> None:
        result = extract_quoted_phrases('"first phrase" and "second phrase"')
        assert "first phrase" in result
        assert "second phrase" in result

    def test_short_phrases_filtered(self) -> None:
        assert extract_quoted_phrases('"ab"') == []
        assert extract_quoted_phrases('"a"') == []

    def test_no_quotes(self) -> None:
        assert extract_quoted_phrases("no quotes here") == []

    def test_empty_string(self) -> None:
        assert extract_quoted_phrases("") == []

    def test_mixed_quote_types(self) -> None:
        result = extract_quoted_phrases("""He said "hello world" and '你好世界'""")
        assert "hello world" in result
        assert "你好世界" in result


class TestExtractPersonNames:
    """Test person name extraction."""

    def test_basic_name(self) -> None:
        assert "John" in extract_person_names("Ask John about this")

    def test_multiple_names(self) -> None:
        result = extract_person_names("Tell Mary and Bob about it")
        assert "Mary" in result
        assert "Bob" in result

    def test_sentence_start_ignored(self) -> None:
        assert extract_person_names("Hello world") == []

    def test_common_words_excluded(self) -> None:
        result = extract_person_names("Ask He and She about Monday")
        assert "He" not in result
        assert "She" not in result
        assert "Monday" not in result

    def test_no_names(self) -> None:
        assert extract_person_names("tell me about python") == []

    def test_empty_string(self) -> None:
        assert extract_person_names("") == []

    def test_punctuation_stripped(self) -> None:
        assert "Alice" in extract_person_names("Ask Alice, please")


class TestExtractTemporalMarkers:
    """Test temporal marker extraction (bilingual)."""

    def test_yesterday(self) -> None:
        assert "yesterday" in extract_temporal_markers("Tell me about yesterday")

    def test_today(self) -> None:
        assert "today" in extract_temporal_markers("What happened today")

    def test_last_week(self) -> None:
        markers = extract_temporal_markers("Show me last week stuff")
        assert any("last week" in m for m in markers)

    def test_days_ago(self) -> None:
        markers = extract_temporal_markers("Something from 3 days ago")
        assert any("3 days ago" in m for m in markers)

    def test_weeks_ago(self) -> None:
        markers = extract_temporal_markers("From 2 weeks ago")
        assert any("2 weeks ago" in m for m in markers)

    def test_chinese_yesterday(self) -> None:
        assert "昨天" in extract_temporal_markers("昨天讨论的方案")

    def test_chinese_day_before(self) -> None:
        assert "前天" in extract_temporal_markers("前天你说的那个事情")

    def test_chinese_today(self) -> None:
        assert "今天" in extract_temporal_markers("今天有什么安排")

    def test_chinese_last_week(self) -> None:
        assert "上周" in extract_temporal_markers("上周的会议内容")

    def test_chinese_last_month(self) -> None:
        assert "上个月" in extract_temporal_markers("上个月的报告")

    def test_chinese_last_year(self) -> None:
        assert "去年" in extract_temporal_markers("去年的项目")

    def test_chinese_recently(self) -> None:
        assert "最近" in extract_temporal_markers("最近学到的东西")

    def test_chinese_n_days_ago(self) -> None:
        markers = extract_temporal_markers("5天前你提到的")
        assert any("5天前" in m for m in markers)

    def test_chinese_n_weeks_ago(self) -> None:
        markers = extract_temporal_markers("2周前的代码")
        assert any("2周前" in m for m in markers)

    def test_chinese_n_months_ago(self) -> None:
        markers = extract_temporal_markers("3个月前的设计")
        assert any("3个月前" in m for m in markers)

    def test_no_temporal(self) -> None:
        assert extract_temporal_markers("What is machine learning") == []

    def test_empty_string(self) -> None:
        assert extract_temporal_markers("") == []


class TestInferReferenceTime:
    """Test reference time inference from temporal markers."""

    def test_yesterday_english(self) -> None:
        ref = infer_reference_time(["yesterday"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=1) - ref).total_seconds()) < 5

    def test_today_english(self) -> None:
        ref = infer_reference_time(["today"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - ref).total_seconds()) < 5

    def test_last_week_english(self) -> None:
        ref = infer_reference_time(["last week"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(weeks=1) - ref).total_seconds()) < 5

    def test_last_month_english(self) -> None:
        ref = infer_reference_time(["last month"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=30) - ref).total_seconds()) < 5

    def test_last_year_english(self) -> None:
        ref = infer_reference_time(["last year"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=365) - ref).total_seconds()) < 5

    def test_n_days_ago_english(self) -> None:
        ref = infer_reference_time(["5 days ago"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=5) - ref).total_seconds()) < 5

    def test_n_weeks_ago_english(self) -> None:
        ref = infer_reference_time(["3 weeks ago"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(weeks=3) - ref).total_seconds()) < 5

    def test_chinese_yesterday(self) -> None:
        ref = infer_reference_time(["昨天"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=1) - ref).total_seconds()) < 5

    def test_chinese_today(self) -> None:
        ref = infer_reference_time(["今天"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - ref).total_seconds()) < 5

    def test_chinese_day_before(self) -> None:
        ref = infer_reference_time(["前天"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=2) - ref).total_seconds()) < 5

    def test_chinese_last_week(self) -> None:
        ref = infer_reference_time(["上周"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(weeks=1) - ref).total_seconds()) < 5

    def test_chinese_last_month(self) -> None:
        ref = infer_reference_time(["上个月"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=30) - ref).total_seconds()) < 5

    def test_chinese_last_year(self) -> None:
        ref = infer_reference_time(["去年"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=365) - ref).total_seconds()) < 5

    def test_chinese_recently(self) -> None:
        ref = infer_reference_time(["最近"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=3) - ref).total_seconds()) < 5

    def test_chinese_n_days_ago(self) -> None:
        ref = infer_reference_time(["5天前"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=5) - ref).total_seconds()) < 5

    def test_chinese_n_weeks_ago(self) -> None:
        ref = infer_reference_time(["2周前"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(weeks=2) - ref).total_seconds()) < 5

    def test_chinese_n_months_ago(self) -> None:
        ref = infer_reference_time(["3个月前"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=90) - ref).total_seconds()) < 5

    def test_empty_list(self) -> None:
        assert infer_reference_time([]) is None

    def test_unrecognized_marker(self) -> None:
        assert infer_reference_time(["some random text"]) is None

    def test_first_marker_used(self) -> None:
        ref = infer_reference_time(["yesterday", "last week"])
        assert ref is not None
        now = datetime.now(UTC)
        assert abs((now - timedelta(days=1) - ref).total_seconds()) < 5


class TestContainsQuotedPhrase:
    """Test quoted phrase matching."""

    def test_exact_match(self) -> None:
        assert contains_quoted_phrase("Hello World is great", "hello world") is True

    def test_case_insensitive(self) -> None:
        assert contains_quoted_phrase("HELLO WORLD", "hello world") is True

    def test_not_found(self) -> None:
        assert contains_quoted_phrase("something else", "hello world") is False


class TestContainsPersonName:
    """Test person name matching."""

    def test_word_boundary(self) -> None:
        assert contains_person_name("Ask John about it", "John") is True

    def test_case_insensitive(self) -> None:
        assert contains_person_name("ask john about it", "John") is True

    def test_partial_no_match(self) -> None:
        assert contains_person_name("Johnny is here", "John") is False

    def test_not_found(self) -> None:
        assert contains_person_name("nothing here", "Alice") is False


class TestIsAssistantReferenceQuery:
    """Test assistant-reference query detection (English and Chinese)."""

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("What did you suggest for testing?", True),
            ("You told me to use pytest", True),
            ("You mentioned this earlier", True),
            ("You recommended a library", True),
            ("Remind me what you said", True),
            ("You provided some examples", True),
            ("You listed three options", True),
            ("You gave me a code snippet", True),
            ("You described the architecture", True),
            ("What did you tell me about databases?", True),
            ("You came up with a good idea", True),
            ("You helped me debug this", True),
            ("You explained the algorithm", True),
            ("Can you remind me your suggestion?", True),
            ("You identified the issue", True),
            ("You said it was a bug", True),
            ("What is machine learning?", False),
            ("Tell me about Python", False),
            ("How do I install npm?", False),
            ("user asked me a question", False),
            ("Someone suggested using Docker", False),
            ("The docs say to do this", False),
        ],
    )
    def test_english_patterns(self, query: str, expected: bool) -> None:
        assert is_assistant_reference_query(query) == expected

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("你建议用什么框架?", True),
            ("你说过这个方案不行", True),
            ("你之前提到过这个问题", True),
            ("你提到的那个库叫什么", True),
            ("你帮我调试过的代码", True),
            ("你推荐的那个工具", True),
            ("你给我写的代码", True),
            ("你解释过的算法", True),
            ("你说的那个方法", True),
            ("你提供的示例", True),
            ("你列的三个选项", True),
            ("提醒我你之前说的", True),
            ("什么是机器学习?", False),
            ("告诉我关于Python的事", False),
        ],
    )
    def test_chinese_patterns(self, query: str, expected: bool) -> None:
        assert is_assistant_reference_query(query) == expected

    def test_case_insensitive(self) -> None:
        assert is_assistant_reference_query("YOU TOLD ME SOMETHING")
        assert is_assistant_reference_query("What Did You Suggest?")

    def test_empty_and_edge_cases(self) -> None:
        assert not is_assistant_reference_query("")
        assert not is_assistant_reference_query("   ")
        assert not is_assistant_reference_query("\\n\\t")


class TestIsPreferenceQuery:
    """Test preference query detection (English and Chinese)."""

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("What do I like for breakfast?", True),
            ("My favorite color?", True),
            ("What do I usually do?", True),
            ("What am I interested in?", True),
            ("What do I dislike?", True),
            ("What do I hate?", True),
            ("What do I want?", True),
            ("What do I need?", True),
            ("What have I been working on?", True),
            ("Remind me what I like", True),
            ("my habit of coding", True),
            ("my belief about AI", True),
            ("my goal this year", True),
            ("Tell me about Python", False),
            ("How do I install npm?", False),
            ("What is machine learning?", False),
        ],
    )
    def test_english_patterns(self, query: str, expected: bool) -> None:
        assert is_preference_query(query) == expected

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("我喜欢什么颜色?", True),
            ("我的偏好是什么?", True),
            ("我通常怎么做?", True),
            ("我习惯用vim", True),
            ("我想要学什么?", True),
            ("我倾向于用Python", True),
            ("我的习惯是什么?", True),
            ("我的目标是什么?", True),
            ("我喜欢用什么编辑器?", True),
            ("我偏好暗色主题", True),
            ("我讨厌写文档", True),
            ("我不喜欢JavaScript", True),
            ("什么是机器学习?", False),
            ("如何安装Python?", False),
        ],
    )
    def test_chinese_patterns(self, query: str, expected: bool) -> None:
        assert is_preference_query(query) == expected


class TestAnalyzeQuery:
    """Test the full analyze_query integration."""

    def test_english_temporal_query(self) -> None:
        ctx = analyze_query("What did John say yesterday?")
        assert isinstance(ctx, QueryContext)
        assert "John" in ctx.person_names
        assert any("yesterday" in m for m in ctx.temporal_markers)
        assert ctx.reference_time is not None

    def test_chinese_temporal_query(self) -> None:
        ctx = analyze_query("昨天讨论的方案是什么")
        assert any("昨天" in m for m in ctx.temporal_markers)
        assert ctx.reference_time is not None

    def test_quoted_phrase_query(self) -> None:
        ctx = analyze_query('Search for "machine learning" articles')
        assert "machine learning" in ctx.quoted_phrases

    def test_preference_query(self) -> None:
        ctx = analyze_query("What do I like for breakfast?")
        assert ctx.is_preference_query is True

    def test_non_preference_query(self) -> None:
        ctx = analyze_query("What is Python?")
        assert ctx.is_preference_query is False

    def test_combined_signals(self) -> None:
        ctx = analyze_query("""Tell Bob about "best practices" from last week""")
        assert "Bob" in ctx.person_names
        assert "best practices" in ctx.quoted_phrases
        assert len(ctx.temporal_markers) > 0
        assert ctx.reference_time is not None

    def test_empty_query(self) -> None:
        ctx = analyze_query("")
        assert ctx.quoted_phrases == []
        assert ctx.person_names == []
        assert ctx.temporal_markers == []
        assert ctx.reference_time is None
        assert ctx.is_preference_query is False
