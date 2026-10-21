"""Tests for the Situation Report builder (cron/situation.py)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.cron.situation import (
    SituationContext,
    SituationReportBuilder,
    SituationSection,
)


def _ctx(last: datetime | None = None) -> SituationContext:
    return SituationContext(
        last_tick_at=last or datetime(2026, 1, 1, tzinfo=UTC),
        agent_id="agent-1",
        user_id="user-1",
    )


class _SimpleSection:
    def __init__(self, name: str, priority: int, body: str | None) -> None:
        self.name = name
        self.priority = priority
        self._body = body

    async def build(self, ctx: SituationContext) -> str | None:
        return self._body


class _FailingSection:
    name = "Broken"
    priority = 1

    async def build(self, ctx: SituationContext) -> str | None:
        raise RuntimeError("db unavailable")


class _SlowSection:
    name = "Slow"
    priority = 5

    async def build(self, ctx: SituationContext) -> str | None:
        await asyncio.sleep(0.01)
        return "I finished"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_builder_rejects_tiny_budget() -> None:
    with pytest.raises(ValueError, match="token_budget must be >= 100"):
        SituationReportBuilder(token_budget=50)


def test_builder_defaults() -> None:
    b = SituationReportBuilder()
    assert b.section_count == 0


# ---------------------------------------------------------------------------
# Empty / no sections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_builder_returns_empty_string() -> None:
    b = SituationReportBuilder()
    assert await b.build(_ctx()) == ""


@pytest.mark.asyncio
async def test_all_sections_return_none() -> None:
    b = SituationReportBuilder()
    b.register(_SimpleSection("A", 1, None))
    b.register(_SimpleSection("B", 2, None))
    assert await b.build(_ctx()) == ""


# ---------------------------------------------------------------------------
# Normal assembly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_section() -> None:
    b = SituationReportBuilder()
    b.register(_SimpleSection("Memory", 10, "3 new items"))
    report = await b.build(_ctx())
    assert "## Memory" in report
    assert "3 new items" in report


@pytest.mark.asyncio
async def test_sections_ordered_by_priority() -> None:
    b = SituationReportBuilder()
    b.register(_SimpleSection("Low", 50, "low body"))
    b.register(_SimpleSection("High", 10, "high body"))
    report = await b.build(_ctx())
    high_pos = report.index("## High")
    low_pos = report.index("## Low")
    assert high_pos < low_pos


@pytest.mark.asyncio
async def test_none_section_is_skipped() -> None:
    b = SituationReportBuilder()
    b.register(_SimpleSection("Present", 1, "content"))
    b.register(_SimpleSection("Absent", 2, None))
    report = await b.build(_ctx())
    assert "## Present" in report
    assert "Absent" not in report


# ---------------------------------------------------------------------------
# Error isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failing_section_skipped_others_present() -> None:
    b = SituationReportBuilder()
    b.register(_FailingSection())
    b.register(_SimpleSection("OK", 10, "works"))
    report = await b.build(_ctx())
    assert "Broken" not in report
    assert "## OK" in report
    assert "works" in report


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_truncation() -> None:
    b = SituationReportBuilder(token_budget=100)
    b.register(_SimpleSection("A", 1, "x" * 500))
    report = await b.build(_ctx())
    assert len(report) <= 100 * 4 + 50  # budget_chars + heading overhead
    assert "[... truncated]" in report


@pytest.mark.asyncio
async def test_budget_drops_excess_sections() -> None:
    b = SituationReportBuilder(token_budget=100)
    b.register(_SimpleSection("First", 1, "a" * 350))
    b.register(_SimpleSection("Second", 2, "b" * 350))
    report = await b.build(_ctx())
    assert "## First" in report
    assert "## Second" not in report


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_build() -> None:
    b = SituationReportBuilder()
    b.register(_SlowSection())
    b.register(_SimpleSection("Fast", 1, "instant"))
    report = await b.build(_ctx())
    assert "## Fast" in report
    assert "## Slow" in report


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_simple_section_is_protocol_conformant() -> None:
    s = _SimpleSection("Test", 1, "body")
    assert isinstance(s, SituationSection)


def test_failing_section_is_protocol_conformant() -> None:
    s = _FailingSection()
    assert isinstance(s, SituationSection)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_none_last_tick_at() -> None:
    """Sections receive None last_tick_at on first-ever heartbeat."""
    ctx = SituationContext(last_tick_at=None, agent_id="a", user_id="u")
    b = SituationReportBuilder()
    b.register(_SimpleSection("S", 1, "content"))
    report = await b.build(ctx)
    assert "## S" in report


@pytest.mark.asyncio
async def test_empty_user_id() -> None:
    """Empty user_id should not crash the builder."""
    ctx = SituationContext(last_tick_at=datetime(2026, 1, 1, tzinfo=UTC), agent_id="a", user_id="")
    b = SituationReportBuilder()
    b.register(_SimpleSection("S", 1, "ok"))
    report = await b.build(ctx)
    assert "ok" in report


@pytest.mark.asyncio
async def test_section_returns_empty_string() -> None:
    """A section returning '' should be treated like content (not skipped)."""
    b = SituationReportBuilder()
    b.register(_SimpleSection("Empty", 1, ""))
    report = await b.build(ctx=_ctx())
    assert "## Empty" in report


@pytest.mark.asyncio
async def test_all_sections_fail() -> None:
    """If all sections fail, report should be empty string."""
    b = SituationReportBuilder()
    b.register(_FailingSection())
    report = await b.build(_ctx())
    assert report == ""


@pytest.mark.asyncio
async def test_unicode_content_in_section() -> None:
    """Unicode content should be handled correctly."""
    b = SituationReportBuilder()
    b.register(_SimpleSection("中文", 1, "这是中文内容 🔥"))
    report = await b.build(_ctx())
    assert "## 中文" in report
    assert "这是中文内容" in report


@pytest.mark.asyncio
async def test_many_sections_priority_stability() -> None:
    """Sections with same priority should not crash; order is stable."""
    b = SituationReportBuilder()
    for i in range(10):
        b.register(_SimpleSection(f"S{i}", 10, f"body{i}"))
    report = await b.build(_ctx())
    for i in range(10):
        assert f"## S{i}" in report


@pytest.mark.asyncio
async def test_budget_exact_fit() -> None:
    """A single section that exactly fills the budget should not be truncated."""
    b = SituationReportBuilder(token_budget=100)
    budget_chars = 100 * 4  # 400 chars
    heading = "## Exact\n"
    body_len = budget_chars - len(heading) - 1  # -1 for trailing newline
    b.register(_SimpleSection("Exact", 1, "x" * body_len))
    report = await b.build(_ctx())
    assert "[... truncated]" not in report
    assert "## Exact" in report


def test_context_is_frozen() -> None:
    """SituationContext should be immutable."""
    ctx = _ctx()
    with pytest.raises(AttributeError):
        ctx.user_id = "hacked"  # type: ignore[misc]
