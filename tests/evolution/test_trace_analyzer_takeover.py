"""Tests for TraceAnalyzer._extract_takeover_evidence."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.event_log.types import EventFilter, EventPayload, StructuredEvent
from myrm_agent_harness.agent.skills.evolution.pipeline.trace_analyzer import TraceAnalyzer


def _make_takeover_event(
    session_id: str = "sess-1",
    seq: int = 1,
    reason: str = "user stuck",
    pre_url: str = "https://example.com/login",
    post_url: str = "https://example.com/dashboard",
    post_aria_tree: str = "main\n  heading 'Dashboard'\n  button 'Logout'",
    duration_s: float = 12.5,
) -> StructuredEvent:
    return StructuredEvent(
        sequence=seq,
        timestamp=time.time(),
        event_type="takeover_trace",
        session_id=session_id,
        data=EventPayload(
            reason=reason,
            pre_url=pre_url,
            post_url=post_url,
            post_aria_tree=post_aria_tree,
            duration_s=duration_s,
        ),
    )


class TestExtractTakeoverEvidence:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_backend(self) -> None:
        analyzer = TraceAnalyzer(backend=None)  # type: ignore[arg-type]
        result = await analyzer._extract_takeover_evidence("sess-1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_events(self) -> None:
        backend = AsyncMock()
        backend.get_events = AsyncMock(return_value=[])
        analyzer = TraceAnalyzer(backend=backend)

        result = await analyzer._extract_takeover_evidence("sess-1")
        assert result == ""
        backend.get_events.assert_called_once_with(
            "sess-1",
            EventFilter(event_types=frozenset({"takeover_trace"})),
        )

    @pytest.mark.asyncio
    async def test_formats_single_event_with_url_change(self) -> None:
        evt = _make_takeover_event()
        backend = AsyncMock()
        backend.get_events = AsyncMock(return_value=[evt])
        analyzer = TraceAnalyzer(backend=backend)

        result = await analyzer._extract_takeover_evidence("sess-1")

        assert "人类接管示范" in result
        assert "user stuck" in result
        assert "https://example.com/login" in result
        assert "https://example.com/dashboard" in result
        assert "12.5s" in result
        assert "Dashboard" in result

    @pytest.mark.asyncio
    async def test_formats_event_with_same_url(self) -> None:
        evt = _make_takeover_event(
            pre_url="https://example.com/page",
            post_url="https://example.com/page",
        )
        backend = AsyncMock()
        backend.get_events = AsyncMock(return_value=[evt])
        analyzer = TraceAnalyzer(backend=backend)

        result = await analyzer._extract_takeover_evidence("sess-1")
        assert "URL 未变, DOM 结构变化" in result

    @pytest.mark.asyncio
    async def test_limits_to_last_3_events(self) -> None:
        events = [_make_takeover_event(seq=i, reason=f"reason-{i}") for i in range(5)]
        backend = AsyncMock()
        backend.get_events = AsyncMock(return_value=events)
        analyzer = TraceAnalyzer(backend=backend)

        result = await analyzer._extract_takeover_evidence("sess-1")

        assert "reason-0" not in result
        assert "reason-1" not in result
        assert "reason-2" in result
        assert "reason-3" in result
        assert "reason-4" in result

    @pytest.mark.asyncio
    async def test_truncates_long_aria_tree(self) -> None:
        long_aria = "a" * 2000
        evt = _make_takeover_event(post_aria_tree=long_aria)
        backend = AsyncMock()
        backend.get_events = AsyncMock(return_value=[evt])
        analyzer = TraceAnalyzer(backend=backend)

        result = await analyzer._extract_takeover_evidence("sess-1")
        assert len(result) < 2000
