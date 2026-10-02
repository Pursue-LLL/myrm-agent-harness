"""Temporal window derivation for time-scoped memory retrieval.

Derives a wide ``(since, until)`` window from natural-language temporal
markers (English + Chinese) in a query, so time-scoped queries such as
“上个月讨论的部署方案” prune candidates at the collect stage instead of
scanning the full library and relying on result-side temporal reweighting
alone.

Design contract (explicit-scope invariance, mirroring ChannelPruner):
- Derivation only fills boundaries when the caller provided neither
  ``since`` nor ``until``; any explicit boundary wins untouched.
- Windows are deliberately wide: each marker's semantic period is padded
  with a spill margin so adjacent-period memories and timezone skew
  (markers resolve against the caller-injected ``now``) survive the hard
  filter. Result-side temporal proximity reweighting (query_analyzer)
  still narrows ranking inside the window: the hard filter prunes, the
  soft reweight ranks.
- Only past-facing markers derive windows; future markers (“明天”,
  “next week”) describe plans rather than recall scope and are ignored,
  as are windows fully in the future (e.g. “今年冬天” asked in autumn
  falls through to the broader “今年” rule instead).

[INPUT]
- (stdlib only - datetime + re)

[OUTPUT]
- TemporalWindow: derived boundaries plus marker metadata for traces
- derive_temporal_window: marker extraction + wide-window derivation

[POS]
Bridges query_analyzer's point-in-time reference scoring (soft, result
side) with the vector stores' since/until hard filters (collect side).
The two systems intentionally overlap: the window only prunes what is
clearly outside the marker's semantic period, never ranks inside it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal

TemporalWindowKind = Literal[
    "day", "week", "month", "quarter", "year", "season", "recent", "relative"
]
"""Marker family of a derived window; drives margin selection and trace labels."""

_WindowResolver = Callable[[datetime, re.Match[str]], tuple[datetime, datetime]]
"""Derives the final wide ``(since, until)`` window from ``now`` + one marker match."""


@dataclass(frozen=True, slots=True)
class TemporalWindow:
    """Hard-filter boundaries derived from one past-facing temporal marker.

    Attributes:
        since: Wide-window lower bound (inclusive), in ``now``'s timezone.
        until: Wide-window upper bound: the period end padded by the kind's
            spill margin, in ``now``'s timezone.
        marker: Matched marker text (trace metadata).
        window_kind: Marker family (trace metadata).
    """

    since: datetime
    until: datetime
    marker: str
    window_kind: TemporalWindowKind


# Spill margins per window family. Wide on purpose: they absorb calendar
# ambiguity, oral sloppiness (“上个月” said on the 1st), and timezone skew
# between the marker's origin and the injected ``now``.
_MARGIN_DAY = timedelta(days=1)
_MARGIN_WEEK = timedelta(days=2)
_MARGIN_MONTH = timedelta(days=5)
_MARGIN_QUARTER = timedelta(days=7)
_MARGIN_YEAR = timedelta(days=15)
_MARGIN_SEASON = timedelta(days=15)
_MARGIN_RECENT = timedelta(days=2)
_RECENT_FALLBACK_SPAN = timedelta(days=30)

_CALENDAR_MARGINS: dict[str, timedelta] = {
    "day": _MARGIN_DAY,
    "week": _MARGIN_WEEK,
    "month": _MARGIN_MONTH,
    "quarter": _MARGIN_QUARTER,
    "year": _MARGIN_YEAR,
}

_SEASON_MONTHS: dict[str, tuple[int, int]] = {
    "spring": (3, 5),
    "summer": (6, 8),
    "autumn": (9, 11),
    "winter": (12, 2),  # spans the year boundary; the end resolves into next year.
}
_SEASON_CANONICAL: dict[str, str] = {
    **dict.fromkeys(("spring", "春天", "春季"), "spring"),
    **dict.fromkeys(("summer", "夏天", "夏季"), "summer"),
    **dict.fromkeys(("autumn", "fall", "秋天", "秋季"), "autumn"),
    **dict.fromkeys(("winter", "冬天", "冬季"), "winter"),
}
_UNIT_DAYS: dict[str, float] = {"day": 1.0, "week": 7.0, "month": 30.0, "year": 365.0}


def _first_of_month(year: int, month: int, tz: tzinfo | None) -> datetime:
    """Month start with overflow normalization (month 13 → next Jan, 0 → prev Dec)."""
    shifted = year * 12 + (month - 1)
    return datetime.combine(date(shifted // 12, shifted % 12 + 1, 1), time.min, tzinfo=tz)


def _month_shift(now: datetime, offset: int) -> tuple[int, int]:
    """``(year, month)`` shifted by whole calendar months."""
    shifted = now.year * 12 + (now.month - 1) + offset
    return shifted // 12, shifted % 12 + 1


def _parse_number(text: str) -> float:
    """Arabic or simple Chinese numeral (1-999) to its numeric value.

    Chinese unit compounds parse positionally: 十二 → 12, 二十 → 20,
    两百三十 → 230. Arabic digits go through unchanged.
    """
    if text.isdigit():
        return float(text)
    digits = {
        "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    total, section = 0, 0
    for ch in text:
        if ch in digits:
            section = digits[ch]
        elif ch == "十":
            total += (section or 1) * 10
            section = 0
        else:  # 百
            total += (section or 1) * 100
            section = 0
    return float(total + section)


def _unit_key(unit_text: str) -> str:
    """Normalize an EN or ZH unit token to its ``_UNIT_DAYS`` key."""
    text = unit_text.lower().replace(" ", "").replace("个", "")
    if text in ("day", "days", "天", "日"):
        return "day"
    if text in ("week", "weeks", "周", "星期"):
        return "week"
    if text in ("month", "months", "月"):
        return "month"
    return "year"


def _calendar_resolver(kind: str, offset: int) -> _WindowResolver:
    """Calendar-anchored window: ``offset`` -1 = previous period, 0 = current.

    Weeks are Monday-anchored; the semantic period is padded by the kind's
    spill margin on both sides so edge-day memories survive the hard filter.
    """

    def resolve(now: datetime, match: re.Match[str]) -> tuple[datetime, datetime]:
        tz = now.tzinfo
        if kind == "day":
            start_day = now.date() + timedelta(days=offset)
            start = datetime.combine(start_day, time.min, tzinfo=tz)
            end = start + timedelta(days=1)
        elif kind == "week":
            monday = now.date() - timedelta(days=now.weekday())
            start = datetime.combine(monday + timedelta(weeks=offset), time.min, tzinfo=tz)
            end = start + timedelta(days=7)
        elif kind == "month":
            y, m = _month_shift(now, offset)
            start = _first_of_month(y, m, tz)
            end = _first_of_month(y, m + 1, tz)
        elif kind == "quarter":
            quarter_first = (now.month - 1) // 3 * 3 + 1
            shifted = now.year * 12 + quarter_first - 1 + offset * 3
            y, m = shifted // 12, shifted % 12 + 1
            start = _first_of_month(y, m, tz)
            end = _first_of_month(y, m + 3, tz)
        else:  # "year"
            start = _first_of_month(now.year + offset, 1, tz)
            end = _first_of_month(now.year + offset + 1, 1, tz)
        margin = _CALENDAR_MARGINS[kind]
        return start - margin, end + margin

    return resolve


def _season_resolver() -> _WindowResolver:
    """Compound season window (“去年春天” / “last spring”): anchor-year months ± 15d."""

    def resolve(now: datetime, match: re.Match[str]) -> tuple[datetime, datetime]:
        season = _SEASON_CANONICAL[match.group("season").lower()]
        year_offset = -1 if match.group("ctx").lower() in ("last", "去年") else 0
        year = now.year + year_offset
        start_month, end_month = _SEASON_MONTHS[season]
        tz = now.tzinfo
        start = _first_of_month(year, start_month, tz)
        # Winter crosses the year boundary: December of the anchor year into
        # February of the next one.
        end = _first_of_month(year if season != "winter" else year + 1, end_month + 1, tz)
        return start - _MARGIN_SEASON, end + _MARGIN_SEASON

    return resolve


def _recent_span_resolver() -> _WindowResolver:
    """Span window (“最近三个月” / “last 3 months”): ``[now - N units, now]`` + 2d spill."""

    def resolve(now: datetime, match: re.Match[str]) -> tuple[datetime, datetime]:
        units = _parse_number(match.group("n"))
        span = timedelta(days=_UNIT_DAYS[_unit_key(match.group("unit"))] * units)
        return now - span - _MARGIN_RECENT, now + _MARGIN_RECENT

    return resolve


def _recent_fallback_resolver() -> _WindowResolver:
    """Bare “最近 / recently”: a 30-day window buys most of the pruning value."""

    def resolve(now: datetime, match: re.Match[str]) -> tuple[datetime, datetime]:
        return now - _RECENT_FALLBACK_SPAN - _MARGIN_RECENT, now + _MARGIN_RECENT

    return resolve


def _relative_resolver() -> _WindowResolver:
    """Point marker (“三天前” / “3 weeks ago”): center ± max(1d, span/4) spill.

    Relative points are fuzzy by nature: “三天前” crosses day boundaries, so
    the spill grows with the unit scale (day → 1d, month → 7.5d, year → 91d).
    """

    def resolve(now: datetime, match: re.Match[str]) -> tuple[datetime, datetime]:
        span_days = _UNIT_DAYS[_unit_key(match.group("unit"))] * _parse_number(match.group("n"))
        center = now - timedelta(days=span_days)
        spill = timedelta(days=max(1.0, span_days / 4))
        return center - spill, center + spill

    return resolve


@dataclass(frozen=True, slots=True)
class _MarkerRule:
    """One temporal marker pattern bound to its window resolver."""

    kind: TemporalWindowKind
    pattern: re.Pattern[str]
    resolve: _WindowResolver


_RULES: tuple[_MarkerRule, ...] = (
    # Compound seasons first: “去年春天” must win over the bare “去年” rule.
    _MarkerRule(
        "season",
        re.compile(
            r"(?P<ctx>去年|今年|last|this)\s*(?P<season>spring|summer|autumn|fall|winter|春天|春季|夏天|夏季|秋天|秋季|冬天|冬季)",
            re.IGNORECASE,
        ),
        _season_resolver(),
    ),
    # Calendar-anchored simple markers, specific before broad.
    _MarkerRule("day", re.compile(r"yesterday|昨天", re.IGNORECASE), _calendar_resolver("day", -1)),
    _MarkerRule("day", re.compile(r"前天"), _calendar_resolver("day", -2)),
    _MarkerRule("day", re.compile(r"today|今天|当天", re.IGNORECASE), _calendar_resolver("day", 0)),
    _MarkerRule(
        "week",
        re.compile(r"last\s+week|previous\s+week|上周|上星期", re.IGNORECASE),
        _calendar_resolver("week", -1),
    ),
    _MarkerRule(
        "week",
        re.compile(r"this\s+week|本周|这周|这一周", re.IGNORECASE),
        _calendar_resolver("week", 0),
    ),
    _MarkerRule(
        "month",
        re.compile(r"last\s+month|previous\s+month|上个月|上月", re.IGNORECASE),
        _calendar_resolver("month", -1),
    ),
    _MarkerRule(
        "month",
        re.compile(r"this\s+month|本月|这个月|当月", re.IGNORECASE),
        _calendar_resolver("month", 0),
    ),
    _MarkerRule(
        "quarter",
        re.compile(r"last\s+quarter|previous\s+quarter|上季度|上个季度", re.IGNORECASE),
        _calendar_resolver("quarter", -1),
    ),
    _MarkerRule(
        "year",
        re.compile(r"last\s+year|previous\s+year|去年", re.IGNORECASE),
        _calendar_resolver("year", -1),
    ),
    _MarkerRule("year", re.compile(r"this\s+year|今年", re.IGNORECASE), _calendar_resolver("year", 0)),
    # Bounded recent spans before the bare fallback: “最近三天” is a 3-day
    # window, not the 30-day one “最近” alone would buy.
    _MarkerRule(
        "recent",
        re.compile(
            r"(?:最近|过去|近期|近)\s*(?P<n>\d{1,3}|[零一二两三四五六七八九十百]{1,4})\s*"
            r"(?P<unit>个\s*月|天|日|周|星期|年)"
        ),
        _recent_span_resolver(),
    ),
    _MarkerRule(
        "recent",
        re.compile(
            r"(?:last|past|in\s+the\s+last)\s+(?P<n>\d{1,3})\s+(?P<unit>days?|weeks?|months?|years?)",
            re.IGNORECASE,
        ),
        _recent_span_resolver(),
    ),
    _MarkerRule(
        "recent",
        re.compile(r"recently|最近|近期|不久前|前段时间|这阵子", re.IGNORECASE),
        _recent_fallback_resolver(),
    ),
    # Relative points. The ZH month unit requires “个” so “3月前” (March)
    # is never mistaken for “三个月前” (three months ago).
    _MarkerRule(
        "relative",
        re.compile(
            r"(?P<n>\d{1,3}|[零一二两三四五六七八九十百]{1,4})\s*"
            r"(?P<unit>个\s*月|天|日|周|星期|年)\s*(?:之?前|以前)"
        ),
        _relative_resolver(),
    ),
    _MarkerRule(
        "relative",
        re.compile(r"(?P<n>\d{1,3})\s+(?P<unit>days?|weeks?|months?|years?)\s+ago", re.IGNORECASE),
        _relative_resolver(),
    ),
)


def derive_temporal_window(query: str, *, now: datetime | None = None) -> TemporalWindow | None:
    """Derive a wide ``(since, until)`` window from the query's first past-facing marker.

    Returns ``None`` when the query carries no temporal marker or the
    matched window starts fully in the future (plans, not recall scope).
    The first match in rule order wins, mirroring query_analyzer's single
    point-of-reference assumption; a skipped future window falls through to
    broader markers (e.g. “今年冬天” in autumn → the “今年” rule).

    Args:
        query: Sanitized retrieval query.
        now: Reference instant; defaults to UTC now. Inject the session
            timezone to anchor calendar boundaries locally — spill margins
            absorb the residual skew either way.
    """
    if not query:
        return None
    reference = now or datetime.now(UTC)
    for rule in _RULES:
        match = rule.pattern.search(query)
        if match is None:
            continue
        since, until = rule.resolve(reference, match)
        if since >= reference:
            continue
        return TemporalWindow(
            since=since, until=until, marker=match.group(0), window_kind=rule.kind
        )
    return None
