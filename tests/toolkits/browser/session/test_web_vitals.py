"""Unit tests for the browser Web Vitals collector."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.session.web_vitals import (
    WebVitalsCollector,
    WebVitalsReport,
    build_suggestions,
    rate_metric,
)


class TestRateMetric:
    def test_good_below_boundary(self) -> None:
        assert rate_metric(2000, (2500, 4000)) == "good"

    def test_good_at_boundary(self) -> None:
        assert rate_metric(2500, (2500, 4000)) == "good"

    def test_needs_improvement(self) -> None:
        assert rate_metric(3000, (2500, 4000)) == "needs-improvement"

    def test_poor(self) -> None:
        assert rate_metric(4500, (2500, 4000)) == "poor"

    def test_none_is_empty(self) -> None:
        assert rate_metric(None, (2500, 4000)) == ""


class TestSuggestions:
    def test_slow_lcp_suggests_resource_fix(self) -> None:
        report = WebVitalsReport(
            url="https://example.com",
            lcp_ms=3000,
            lcp_url="https://cdn.example.com/hero.jpg",
        )
        suggestions = build_suggestions(report)
        assert any("hero.jpg" in s and "LCP" in s for s in suggestions)

    def test_slow_lcp_without_url_suggests_render_path(self) -> None:
        report = WebVitalsReport(url="https://example.com", lcp_ms=3000)
        suggestions = build_suggestions(report)
        assert any("initial render path" in s for s in suggestions)

    def test_good_lcp_without_url_no_suggestion(self) -> None:
        report = WebVitalsReport(url="https://example.com", lcp_ms=1000)
        assert build_suggestions(report) == []

    def test_slow_ttfb_suggests_cdn(self) -> None:
        report = WebVitalsReport(url="https://example.com", ttfb_ms=1200)
        suggestions = build_suggestions(report)
        assert any("TTFB" in s and "CDN" in s for s in suggestions)

    def test_layout_shift_suggests_reserved_space(self) -> None:
        report = WebVitalsReport(url="https://example.com", cls=0.3)
        suggestions = build_suggestions(report)
        assert any("Layout shift" in s for s in suggestions)

    def test_slow_inp_suggests_main_thread(self) -> None:
        report = WebVitalsReport(url="https://example.com", inp_ms=600)
        suggestions = build_suggestions(report)
        assert any("main-thread" in s for s in suggestions)

    def test_concentrated_slow_resources_suggest_preconnect(self) -> None:
        report = WebVitalsReport(
            url="https://example.com",
            slow_resources=[
                {"name": "https://slow-cdn.com/a.js", "duration": 3000, "size": 0, "type": "script"},
                {"name": "https://slow-cdn.com/b.js", "duration": 2500, "size": 0, "type": "script"},
            ],
        )
        suggestions = build_suggestions(report)
        assert any("slow-cdn.com" in s for s in suggestions)

    def test_no_suggestions_for_good_metrics(self) -> None:
        report = WebVitalsReport(
            url="https://example.com",
            lcp_ms=1500,
            cls=0.02,
            inp_ms=80,
            fcp_ms=800,
            ttfb_ms=300,
        )
        assert build_suggestions(report) == []


class TestReportText:
    def test_format_includes_all_metric_lines(self) -> None:
        report = WebVitalsReport(
            url="https://example.com",
            lcp_ms=2800,
            cls=0.31,
            inp_ms=None,
            fcp_ms=1900,
            ttfb_ms=1200,
        )
        text = report.to_text()
        assert "Web Vitals for https://example.com" in text
        assert "LCP  2800ms" in text
        assert "needs-improvement" in text or "Poor" in text
        assert "interact with the page and re-check" in text

    def test_format_lists_slow_resources(self) -> None:
        report = WebVitalsReport(
            url="https://example.com",
            slow_resources=[
                {"name": "https://cdn.example.com/main.js", "duration": 2400, "size": 512, "type": "script"}
            ],
            suggestions=["Test suggestion."],
        )
        text = report.to_text()
        assert "Slow resources:" in text
        assert "cdn.example.com/main.js" in text
        assert "Suggestions:" in text
        assert "Test suggestion." in text

    def test_format_truncates_long_url(self) -> None:
        long_url = "https://cdn.example.com/" + "a" * 500 + ".js"
        report = WebVitalsReport(
            url="https://example.com",
            slow_resources=[{"name": long_url, "duration": 2400, "size": 0, "type": "script"}],
        )
        text = report.to_text()
        assert long_url not in text
        assert "…" in text

    def test_format_tolerates_missing_resource_fields(self) -> None:
        report = WebVitalsReport(
            url="https://example.com",
            slow_resources=[{"name": "https://cdn.example.com/missing.js"}],
        )
        text = report.to_text()
        assert "missing.js" in text


def _mock_page(return_value: dict) -> MagicMock:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=return_value)
    return page


class TestCollector:
    @pytest.mark.asyncio
    async def test_collect_parses_payload(self) -> None:
        page = _mock_page(
            {
                "lcp": 2100,
                "lcpUrl": "https://cdn.example.com/hero.png",
                "cls": 0.05,
                "inp": 150,
                "fcp": 900,
                "ttfb": 400,
                "resources": [
                    {"name": "https://cdn.example.com/main.js", "duration": 1200, "size": 0, "type": "script"}
                ],
            }
        )
        with patch("myrm_agent_harness.toolkits.browser.session.web_vitals._RETRY_WAIT_S", 0.0):
            report = await WebVitalsCollector().collect(page, "https://example.com")
        assert report.lcp_ms == 2100
        assert report.lcp_url == "https://cdn.example.com/hero.png"
        assert report.cls == 0.05
        assert report.inp_ms == 150
        assert report.fcp_ms == 900
        assert report.ttfb_ms == 400
        assert report.slow_resources[0]["name"] == "https://cdn.example.com/main.js"

    @pytest.mark.asyncio
    async def test_collect_retries_when_lcp_pending(self) -> None:
        page = MagicMock()
        page.evaluate = AsyncMock(
            side_effect=[
                {"lcp": None, "cls": None, "inp": None, "fcp": None, "ttfb": None, "resources": []},
                {
                    "lcp": 3200,
                    "lcpUrl": "https://cdn.example.com/hero.jpg",
                    "cls": None,
                    "inp": None,
                    "fcp": 1200,
                    "ttfb": 500,
                    "resources": [],
                },
            ]
        )
        with patch("myrm_agent_harness.toolkits.browser.session.web_vitals._RETRY_WAIT_S", 0.0):
            report = await WebVitalsCollector().collect(page, "https://example.com")
        assert report.lcp_ms == 3200
        assert page.evaluate.await_count == 2

    @pytest.mark.asyncio
    async def test_collect_retry_failure_degrades_to_empty_report(self) -> None:
        page = MagicMock()
        page.evaluate = AsyncMock(
            side_effect=[
                {"lcp": None, "cls": None, "inp": None, "fcp": None, "ttfb": None, "resources": []},
                RuntimeError("page closed during retry"),
            ]
        )
        with patch("myrm_agent_harness.toolkits.browser.session.web_vitals._RETRY_WAIT_S", 0.0):
            report = await WebVitalsCollector().collect(page, "https://example.com")
        assert report.lcp_ms is None
        assert report.slow_resources == []
        assert "Web Vitals for https://example.com" in report.to_text()
        assert page.evaluate.await_count == 2

    @pytest.mark.asyncio
    async def test_collect_degrades_when_page_unavailable(self) -> None:
        page = MagicMock()
        page.evaluate = AsyncMock(side_effect=RuntimeError("page closed"))
        with patch("myrm_agent_harness.toolkits.browser.session.web_vitals._RETRY_WAIT_S", 0.0):
            report = await WebVitalsCollector().collect(page, "https://example.com")
        assert report.lcp_ms is None
        assert report.cls is None
        assert "Web Vitals for https://example.com" in report.to_text()
        assert page.evaluate.await_count == 1

    @pytest.mark.asyncio
    async def test_collect_ignores_non_dict_payload(self) -> None:
        page = _mock_page(["not", "a", "dict"])
        with patch("myrm_agent_harness.toolkits.browser.session.web_vitals._RETRY_WAIT_S", 0.0):
            report = await WebVitalsCollector().collect(page, "https://example.com")
        assert report.lcp_ms is None
        assert report.slow_resources == []
        assert page.evaluate.await_count == 1
