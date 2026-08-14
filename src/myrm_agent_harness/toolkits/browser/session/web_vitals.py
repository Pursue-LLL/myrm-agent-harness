"""On-demand Core Web Vitals collection for a loaded page.

[INPUT]
- patchright.async_api::Page (POS: fully loaded page instance)

[OUTPUT]
- rate_metric: value -> official rating bucket ("good"/"needs-improvement"/"poor"/"")
- WebVitalsReport: dataclass holding raw values, ratings, suggestions, text
- WebVitalsCollector: one-shot collector (evaluate -> parse -> grade -> suggest)
- build_suggestions: derive actionable fix suggestions from measured values

[POS]
Reads buffered PerformanceObserver history (LCP/CLS/INP) plus NavigationTiming
(FCP/TTFB) and ResourceTiming (slow-resource attribution) in a single
``page.evaluate`` round-trip. No resident listeners and no lifecycle hooks:
navigation is already complete when the agent asks for metrics, so buffered
entries are sufficient. Ratings follow the official Core Web Vitals thresholds;
values are real-world measurements of the current environment, never
lab-simulated, which the report states explicitly. The injected script is a
static, self-contained string — the page is only read, never mutated.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page

logger = logging.getLogger(__name__)

_MAX_SLOW_RESOURCES = 8
_RETRY_WAIT_S = 1.0

# Official Core Web Vitals thresholds (good / needs-improvement boundary pairs).
_LCP_THRESHOLDS = (2500, 4000)
_CLS_THRESHOLDS = (0.1, 0.25)
_INP_THRESHOLDS = (200, 500)
_FCP_THRESHOLDS = (1800, 3000)
_TTFB_THRESHOLDS = (800, 1800)

_COLLECT_JS = r"""
() => new Promise((resolve) => {
  const out = {
    ttfb: null, fcp: null, lcp: null, lcpUrl: null, cls: null, inp: null, resources: []
  };
  let resolved = false;
  const finish = () => {
    if (resolved) return;
    resolved = true;
    try {
      const res = performance.getEntriesByType('resource');
      res.sort((a, b) => (b.duration || 0) - (a.duration || 0));
      out.resources = res.slice(0, __MAX_SLOW_RESOURCES__).map(r => ({
        name: r.name, duration: Math.round(r.duration || 0),
        size: r.transferSize || 0, type: r.initiatorType || ''
      }));
    } catch (e) {}
    resolve(out);
  };

  try {
    const nav = performance.getEntriesByType('navigation')[0];
    if (nav) out.ttfb = Math.round(nav.responseStart);
  } catch (e) {}
  try {
    const paints = performance.getEntriesByType('paint');
    const fcp = paints.find(e => e.name === 'first-contentful-paint');
    if (fcp) out.fcp = Math.round(fcp.startTime);
  } catch (e) {}

  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length) {
        const last = entries[entries.length - 1];
        out.lcp = Math.round(last.startTime);
        out.lcpUrl = last.url || null;
      }
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch (e) {}

  try {
    let cls = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (!e.hadRecentInput) cls += e.value;
      }
      out.cls = Math.round(cls * 1000) / 1000;
    }).observe({ type: 'layout-shift', buffered: true });
  } catch (e) {}

  try {
    let worst = 0;
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) {
        if (e.duration > worst) worst = e.duration;
      }
      if (worst > 0) out.inp = Math.round(worst);
    }).observe({ type: 'event', durationThreshold: 16, buffered: true });
  } catch (e) {}

  // Buffered observers are delivered in separate tasks; finishing inside a
  // callback could resolve before later observers write their data. A single
  // timer collects every observer's buffered snapshot before resolving.
  setTimeout(finish, 120);
})
""".replace("__MAX_SLOW_RESOURCES__", str(_MAX_SLOW_RESOURCES))


def rate_metric(value: float | None, thresholds: tuple[float, float]) -> str:
    """Map a metric value to its official rating bucket.

    Args:
        value: Raw metric value (seconds/score). None maps to the empty string
            (metric not measurable yet).
        thresholds: (good_upper, needs_improvement_upper) boundary pair.

    Returns:
        "good", "needs-improvement", "poor", or "" when value is None.
    """
    if value is None:
        return ""
    good_upper, ni_upper = thresholds
    if value <= good_upper:
        return "good"
    if value <= ni_upper:
        return "needs-improvement"
    return "poor"


@dataclass(frozen=True, slots=True)
class WebVitalsReport:
    """Collected metrics for one page with ratings and actionable suggestions.

    Attributes:
        url: Page URL at collection time.
        lcp_ms: Largest Contentful Paint in ms, or None if not determinable.
        lcp_url: URL of the largest contentful resource (when reported).
        cls: Cumulative Layout Shift score, or None.
        inp_ms: Interaction to Next Paint in ms, or None (needs interaction).
        fcp_ms: First Contentful Paint in ms, or None.
        ttfb_ms: Time To First Byte in ms, or None.
        slow_resources: Top slow resources by duration (name, ms, bytes, type).
        suggestions: Actionable fix suggestions derived from the readings.
    """

    url: str
    lcp_ms: int | None = None
    lcp_url: str | None = None
    cls: float | None = None
    inp_ms: int | None = None
    fcp_ms: int | None = None
    ttfb_ms: int | None = None
    slow_resources: list[dict[str, object]] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Render the report as a compact text block for the agent."""
        lines = [
            f"Web Vitals for {self.url} (measured in the current network environment)",
        ]
        metrics = (
            ("LCP", self.lcp_ms, "ms", _LCP_THRESHOLDS),
            ("CLS", self.cls, "", _CLS_THRESHOLDS),
            ("INP", self.inp_ms, "ms", _INP_THRESHOLDS),
            ("FCP", self.fcp_ms, "ms", _FCP_THRESHOLDS),
            ("TTFB", self.ttfb_ms, "ms", _TTFB_THRESHOLDS),
        )
        for name, value, unit, thresholds in metrics:
            if value is None:
                note = "not measurable yet — interact with the page and re-check" if name == "INP" else "not available"
                lines.append(f"{name}  n/a    —     {note}")
                continue
            rating = rate_metric(value, thresholds)
            lines.append(f"{name}  {value}{unit:<4} {rating}")

        if self.slow_resources:
            lines.append("Slow resources:")
            for res in self.slow_resources[:_MAX_SLOW_RESOURCES]:
                name = _truncate_url(str(res.get("name", "")))
                duration = res.get("duration", 0)
                res_type = res.get("type", "")
                size = res.get("size", 0)
                lines.append(f"  - {name} — {duration}ms ({res_type}{', ' + str(size) + 'B' if size else ''})")
        if self.suggestions:
            lines.append("Suggestions:")
            for suggestion in self.suggestions:
                lines.append(f"  - {suggestion}")
        return "\n".join(lines)


class WebVitalsCollector:
    """One-shot Core Web Vitals collector bound to no persistent state."""

    async def collect(self, page: Page, url: str) -> WebVitalsReport:
        """Collect and grade Web Vitals for the given loaded page.

        Retries once after a short wait when LCP has not been finalized yet
        (SPA navigations can settle the largest paint late).

        Args:
            page: Loaded page to measure.
            url: Page URL to attach to the report.

        Returns:
            A fully parsed WebVitalsReport; failures degrade to an empty report
            with a descriptive suggestion instead of raising.
        """
        raw = await self._collect_once(page)
        if raw and raw.get("lcp") is None:
            await asyncio.sleep(_RETRY_WAIT_S)
            raw = await self._collect_once(page) or {}

        report = self._build_report(raw, url)
        return replace(report, suggestions=build_suggestions(report))

    async def _collect_once(self, page: Page) -> dict[str, object]:
        try:
            result = await page.evaluate(_COLLECT_JS)
        except Exception as exc:
            logger.warning("Web Vitals collection failed (page context unavailable): %s", exc)
            return {}
        if not isinstance(result, dict):
            logger.warning("Web Vitals collection returned unexpected payload: %r", result)
            return {}
        return result

    @staticmethod
    def _build_report(raw: dict[str, object], url: str) -> WebVitalsReport:
        return WebVitalsReport(
            url=url,
            lcp_ms=_as_int(raw.get("lcp")),
            lcp_url=_as_str(raw.get("lcpUrl")),
            cls=_as_float(raw.get("cls")),
            inp_ms=_as_int(raw.get("inp")),
            fcp_ms=_as_int(raw.get("fcp")),
            ttfb_ms=_as_int(raw.get("ttfb")),
            slow_resources=[res for res in raw.get("resources", []) if isinstance(res, dict) and "name" in res],
        )


def build_suggestions(report: WebVitalsReport) -> list[str]:
    """Derive actionable suggestions from the measured values (Lighthouse-style
    attribution: numbers without a fix are not useful to the user)."""
    suggestions: list[str] = []

    lcp_poor = report.lcp_ms is not None and rate_metric(report.lcp_ms, _LCP_THRESHOLDS) in (
        "needs-improvement",
        "poor",
    )
    if lcp_poor:
        if report.lcp_url:
            suggestions.append(
                f"LCP is driven by {_truncate_url(report.lcp_url)} — compress it, lazy-load "
                "below-the-fold content, or preload the critical image/font."
            )
        else:
            suggestions.append(
                "Slow LCP without an attributable resource — optimize the initial render "
                "path: inline critical CSS and remove render-blocking scripts."
            )
    if report.ttfb_ms is not None and rate_metric(report.ttfb_ms, _TTFB_THRESHOLDS) in (
        "needs-improvement",
        "poor",
    ):
        suggestions.append("High TTFB — enable CDN caching and server-side response caching to cut first-byte latency.")
    if report.cls is not None and rate_metric(report.cls, _CLS_THRESHOLDS) in (
        "needs-improvement",
        "poor",
    ):
        suggestions.append(
            "Layout shift detected — reserve explicit width/height for images, ads, and "
            "iframes so the page does not jump while loading."
        )
    if report.inp_ms is not None and rate_metric(report.inp_ms, _INP_THRESHOLDS) == "poor":
        suggestions.append(
            "Slow interaction response — reduce main-thread blocking (long tasks) and defer non-critical JavaScript."
        )

    if report.slow_resources:
        domains: dict[str, int] = {}
        for res in report.slow_resources:
            name = str(res.get("name", ""))
            domain = name.split("/")[2] if name.startswith(("http://", "https://")) else ""
            if domain:
                domains[domain] = domains.get(domain, 0) + 1
        top_domain = max(domains.items(), key=lambda item: item[1], default=None)
        if top_domain and top_domain[1] >= 2:
            suggestions.append(
                f"Multiple slow resources come from {top_domain[0]} — consider "
                "preconnecting or moving it to a faster host."
            )
    return suggestions


def _as_int(value: object) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _truncate_url(url: str, max_len: int = 200) -> str:
    """Keep URLs readable in the report without blowing up the token budget."""
    return url if len(url) <= max_len else url[: max_len - 1] + "…"
