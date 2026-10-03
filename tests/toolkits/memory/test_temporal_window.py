"""Temporal window derivation tests.

Covers every marker family (day/week/month/quarter/year/season/recent/
relative), bilingual markers, calendar-edge anchoring, the future-window
fall-through guard, and the March-vs-months disambiguation.
"""

from datetime import UTC, datetime, timedelta, timezone

from myrm_agent_harness.toolkits.memory._internal.temporal_window import (
    _unit_key,
    derive_temporal_window,
)

# Fixed Friday evening: every calendar edge below is deterministic.
NOW = datetime(2026, 10, 2, 21, 0, tzinfo=UTC)


def _derive(query: str):
    return derive_temporal_window(query, now=NOW)


def test_no_marker_returns_none() -> None:
    assert _derive("部署方案的技术选型") is None
    assert _derive("what is our deployment plan") is None


def test_empty_query_returns_none() -> None:
    assert derive_temporal_window("", now=NOW) is None


def test_yesterday_zh() -> None:
    window = _derive("昨天部署的服务怎么样")
    assert window is not None
    assert window.marker == "昨天"
    assert window.window_kind == "day"
    yesterday = NOW - timedelta(days=1)
    assert window.since < yesterday < window.until


def test_yesterday_en() -> None:
    window = _derive("what did we discuss yesterday")
    assert window is not None
    assert window.marker == "yesterday"
    assert window.window_kind == "day"


def test_day_before_yesterday() -> None:
    window = _derive("前天的会议记录")
    assert window is not None
    assert window.window_kind == "day"
    two_days_ago = NOW - timedelta(days=2)
    assert window.since < two_days_ago < window.until


def test_last_week_is_monday_anchored() -> None:
    window = _derive("上周讨论的架构方案")
    assert window is not None
    assert window.window_kind == "week"
    # Now is Friday 2026-10-02; last week is 2026-09-21 (Mon) .. 2026-09-27 (Sun).
    last_monday = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    last_sunday = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    assert window.since < last_monday
    assert window.until > last_sunday


def test_last_month_covers_previous_calendar_month() -> None:
    window = _derive("上个月讨论的部署方案")
    assert window is not None
    assert window.marker == "上个月"
    assert window.window_kind == "month"
    mid_september = datetime(2026, 9, 15, tzinfo=UTC)
    assert window.since < mid_september < window.until
    # The wide window must not bleed into August without margin: mid-August
    # stays outside the semantic month even with the 5-day spill.
    assert window.since > datetime(2026, 8, 20, tzinfo=UTC)


def test_last_quarter_covers_previous_calendar_quarter() -> None:
    window = _derive("上季度的复盘结论")
    assert window is not None
    assert window.window_kind == "quarter"
    # Now is 2026-10-02 (Q4); last quarter is Q3: 2026-07-01 .. 2026-09-30.
    q3_start = datetime(2026, 7, 1, tzinfo=UTC)
    q3_end = datetime(2026, 9, 30, 23, 0, tzinfo=UTC)
    assert window.since < q3_start
    assert window.until > q3_end


def test_last_year_and_this_year() -> None:
    last_year = _derive("去年的目标回顾")
    assert last_year is not None
    assert last_year.window_kind == "year"
    mid_2025 = datetime(2025, 6, 15, tzinfo=UTC)
    assert last_year.since < mid_2025 < last_year.until

    this_year = _derive("今年做过的重要决定")
    assert this_year is not None
    assert this_year.window_kind == "year"
    mid_2026 = datetime(2026, 3, 15, tzinfo=UTC)
    assert this_year.since < mid_2026 < this_year.until


def test_season_compound_last_spring() -> None:
    window = _derive("去年春天的招聘计划")
    assert window is not None
    assert window.marker == "去年春天"
    assert window.window_kind == "season"
    mid_spring_2025 = datetime(2025, 4, 15, tzinfo=UTC)
    assert window.since < mid_spring_2025 < window.until


def test_season_compound_last_summer_en() -> None:
    window = _derive("what we built last summer")
    assert window is not None
    assert window.window_kind == "season"
    mid_summer_2025 = datetime(2025, 7, 15, tzinfo=UTC)
    assert window.since < mid_summer_2025 < window.until


def test_season_last_winter_spans_year_boundary() -> None:
    window = _derive("去年冬天的出行安排")
    assert window is not None
    assert window.window_kind == "season"
    # Winter: 2025-12 .. 2026-02, crossing the year boundary.
    january_2026 = datetime(2026, 1, 15, tzinfo=UTC)
    assert window.since < january_2026 < window.until


def test_future_season_falls_through_to_broader_year() -> None:
    # Asked in autumn, "今年冬天" starts in the future: not a recall scope.
    # The guard skips the season window and the bare "今年" rule applies.
    window = _derive("今年冬天的计划")
    assert window is not None
    assert window.window_kind == "year"
    assert window.marker == "今年"


def test_future_markers_are_ignored() -> None:
    assert _derive("明天的会议安排") is None
    assert _derive("next week we will deploy") is None


def test_recent_span_zh_and_en() -> None:
    zh = _derive("最近三个月的迭代记录")
    assert zh is not None
    assert zh.window_kind == "recent"
    assert zh.since < NOW - timedelta(days=90) < zh.until

    en = _derive("errors seen in the last 3 months")
    assert en is not None
    assert en.window_kind == "recent"
    assert en.since < NOW - timedelta(days=90) < en.until


def test_recent_bare_fallback_is_thirty_days() -> None:
    window = _derive("最近的进展")
    assert window is not None
    assert window.window_kind == "recent"
    assert window.since < NOW - timedelta(days=30) < window.until
    assert window.since > NOW - timedelta(days=35)

    en = _derive("recently changed configs")
    assert en is not None
    assert en.window_kind == "recent"


def test_relative_point_zh_and_en() -> None:
    zh = _derive("三天前改的配置")
    assert zh is not None
    assert zh.window_kind == "relative"
    three_days_ago = NOW - timedelta(days=3)
    assert zh.since < three_days_ago < zh.until

    en = _derive("the incident 3 weeks ago")
    assert en is not None
    assert en.window_kind == "relative"
    three_weeks_ago = NOW - timedelta(days=21)
    assert en.since < three_weeks_ago < en.until


def test_relative_month_requires_ge_counter() -> None:
    # "3月前" reads as March; it must NOT become a three-months-ago window.
    assert _derive("3月前定的计划") is None
    # "三个月之前" is unambiguous and matches.
    window = _derive("三个月之前聊过的候选人")
    assert window is not None
    assert window.window_kind == "relative"


def test_timezone_aware_reference() -> None:
    shanghai_now = NOW.astimezone(timezone(timedelta(hours=8)))
    window = derive_temporal_window("昨天部署的服务", now=shanghai_now)
    assert window is not None
    assert window.since.tzinfo is not None
    assert window.until.tzinfo is not None
    # Same instant semantics: the UTC "now" yesterday falls inside.
    yesterday_utc = NOW - timedelta(days=1)
    assert window.since < yesterday_utc < window.until


def test_first_rule_in_priority_order_wins() -> None:
    window = _derive("上周和昨天都聊过这个")
    # The day rule precedes the week rule in the table, so the window kind
    # is "day" regardless of marker position in the query.
    assert window is not None
    assert window.window_kind == "day"


def test_compound_chinese_numerals_parse_to_days() -> None:
    # "三十天前" (30) and "一百天前" (100) exercise the compound numeral
    # branch (十/百 positional parsing), not the single-digit table.
    window = _derive("三十天前定的方案")
    assert window is not None
    assert window.window_kind == "relative"
    thirty_days_ago = NOW - timedelta(days=30)
    assert window.since < thirty_days_ago < window.until

    window = _derive("一百天前提到的服务器")
    assert window is not None
    hundred_days_ago = NOW - timedelta(days=100)
    assert window.since < hundred_days_ago < window.until


def test_unit_key_maps_unmapped_unit_to_year_span() -> None:
    # Defensive fallback: the relative unit patterns only admit tokens already
    # present in _UNIT_DAYS; a future token outside the table must stay usable
    # (year span) instead of raising on the retrieval path.
    assert _unit_key("quarter") == "year"
