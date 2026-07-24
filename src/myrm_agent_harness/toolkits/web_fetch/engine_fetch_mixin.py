"""FetchEngine fetch, degradation, and router feedback helpers.

[POS]
Mixin: L1/L2/L3 fetch+pipeline, tier degradation, adaptive router feedback.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from .antibot_detector import is_blocked as detect_antibot
from .engine_types import DEGRADABLE_4XX
from .fetchers.protocols import FetcherType, FetchResult

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine

logger = logging.getLogger(__name__)

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except (ImportError, TypeError):
    _PSUTIL_AVAILABLE = False
    logger.warning("psutil not available, resource tracking disabled")


class FetchEngineFetchMixin:
    async def _try_fetch_and_process(
        self: FetchEngine,
        url: str,
        fetcher_type: FetcherType,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_chars: int = 0,
    ) -> tuple[Document | None, bool, float, float | None, float | None, FetchResult | None]:
        """Fetch with a specified fetcher and process through the pipeline."""
        fetcher_map = {
            FetcherType.HTTP: self._http_fetcher,
            FetcherType.BROWSER: self._browser_fetcher,
            FetcherType.STEALTH: self._stealth_fetcher,
        }
        fetcher = fetcher_map[fetcher_type]

        if fetcher_type == FetcherType.BROWSER:
            from .escalation.context import get_bound_browser_launch_mode

            launch_mode = get_bound_browser_launch_mode()
            if launch_mode is None:
                launch_mode = self._browser_launch_mode
            self._browser_fetcher.set_launch_mode_preference(launch_mode)

        if _PSUTIL_AVAILABLE:
            process = psutil.Process()
            cpu_times_start = process.cpu_times()
            mem_start_mb = process.memory_info().rss / 1024 / 1024
        else:
            cpu_times_start = None
            mem_start_mb = None

        start_time = time.time()
        if fetcher_type == FetcherType.HTTP and (etag or last_modified):
            fetch_result: FetchResult | None = await fetcher.fetch(url, etag=etag, last_modified=last_modified)
        else:
            fetch_result = await fetcher.fetch(url)
        elapsed = time.time() - start_time
        latency_ms = elapsed * 1000.0

        if _PSUTIL_AVAILABLE and cpu_times_start is not None and mem_start_mb is not None:
            cpu_times_end = process.cpu_times()
            cpu_used = (cpu_times_end.user - cpu_times_start.user) + (cpu_times_end.system - cpu_times_start.system)
            cpu_percent = (cpu_used / elapsed * 100.0) if elapsed > 0 else 0.0
            mem_delta_mb = (process.memory_info().rss / 1024 / 1024) - mem_start_mb
            cpu_percent = max(0.0, cpu_percent)
            memory_mb = max(0.0, mem_delta_mb)
        else:
            cpu_percent = None
            memory_mb = None

        if fetch_result is None:
            return None, True, latency_ms, cpu_percent, memory_mb, None

        if fetch_result.status_code == 304:
            logger.info(f"HTTP 304 Not Modified: {url}")
            return None, False, latency_ms, cpu_percent, memory_mb, fetch_result

        if (
            fetcher_type == FetcherType.HTTP
            and 400 <= fetch_result.status_code < 500
            and fetch_result.status_code not in DEGRADABLE_4XX
        ):
            logger.warning(f"HTTP {fetch_result.status_code} not degradable, abort: {url}")
            return None, False, latency_ms, cpu_percent, memory_mb, None

        if fetcher_type == FetcherType.HTTP and not fetch_result.has_content:
            logger.warning(f"L1 HTTP returned empty shell, will degrade: {url}")
            return None, True, latency_ms, cpu_percent, memory_mb, None

        if fetch_result.raw_body is not None:
            from .binary_router import route_binary_content

            doc = await route_binary_content(fetch_result.raw_body, fetch_result.headers, url)
            return doc, False, latency_ms, cpu_percent, memory_mb, fetch_result

        blocked, reason = detect_antibot(fetch_result.status_code, fetch_result.html)
        if blocked:
            logger.warning(f"Anti-bot detected ({reason}): {url}")
            return None, True, latency_ms, cpu_percent, memory_mb, None

        doc = self._pipeline.process(fetch_result, max_chars=max_chars)

        if doc and doc.metadata.get("was_truncated"):
            try:
                from myrm_agent_harness.utils.event_utils import dispatch_custom_event

                await dispatch_custom_event(
                    "agent_status",
                    {
                        "step_key": "ux_warning_truncated",
                        "status": "warning",
                        "items": [
                            {
                                "text": f"Warning: Content from {url} was intelligently truncated to fit within context limits."
                            }
                        ],
                        "metadata": {"type": "html_truncation", "url": url},
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to dispatch truncation event: {e}")

        return doc, True, latency_ms, cpu_percent, memory_mb, fetch_result

    async def _try_and_report(
        self: FetchEngine,
        url: str,
        fetcher_type: FetcherType,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_chars: int = 0,
    ) -> tuple[Document | None, bool, float, float | None, float | None, FetchResult | None]:
        """Attempt fetch and auto-report result to router."""
        doc, degradable, latency, cpu, mem, fetch_result = await self._try_fetch_and_process(
            url, fetcher_type, etag=etag, last_modified=last_modified, max_chars=max_chars
        )
        self._report_feedback(url, fetcher_type, success=(doc is not None), latency_ms=latency, cpu=cpu, memory=mem)
        return doc, degradable, latency, cpu, mem, fetch_result

    async def _crawl_with_degradation(
        self: FetchEngine,
        url: str,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
        max_chars: int = 0,
        allow_escalation: bool = True,
    ) -> tuple[Document | None, FetchResult | None]:
        """Smart degradation: select starting tier from routing result, degrade tier by tier."""
        decision = self._router.select(url)
        start_type = decision.fetcher_type

        if start_type == FetcherType.STEALTH:
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.STEALTH, max_chars=max_chars)
            if doc:
                return doc, result

            logger.warning(f"Stealth failed, trying browser: {url}")
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.BROWSER, max_chars=max_chars)
            if doc:
                return doc, result
            if allow_escalation:
                esc_doc, esc_result = await self._try_escalation(url, max_chars=max_chars)
                if esc_doc:
                    return esc_doc, esc_result
            return doc, result

        if start_type == FetcherType.BROWSER:
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.BROWSER, max_chars=max_chars)
            if doc:
                return doc, result

            logger.warning(f"Browser failed, trying stealth: {url}")
            doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.STEALTH, max_chars=max_chars)
            if doc:
                return doc, result
            if allow_escalation:
                esc_doc, esc_result = await self._try_escalation(url, max_chars=max_chars)
                if esc_doc:
                    return esc_doc, esc_result
            return doc, result

        doc, degradable, _, _, _, result = await self._try_and_report(
            url, FetcherType.HTTP, etag=etag, last_modified=last_modified, max_chars=max_chars
        )
        if doc or not degradable:
            return doc, result

        logger.warning(f"HTTP insufficient, degrading to browser: {url}")
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                "agent_status",
                {
                    "event": "tool_fallback",
                    "tool": "web_fetch_tool",
                    "fallback_type": "antibot_bypass",
                    "message": "触发反爬防御，正在切换至无头浏览器模拟模式...",
                },
            )
        except Exception:
            pass

        doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.BROWSER, max_chars=max_chars)
        if doc:
            return doc, result

        logger.warning(f"Browser failed, degrading to stealth: {url}")
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                "agent_status",
                {
                    "event": "tool_fallback",
                    "tool": "web_fetch_tool",
                    "fallback_type": "stealth_bypass",
                    "message": "浏览器模式受阻，正在切换至深度隐身模式...",
                },
            )
        except Exception:
            pass

        doc, _, _, _, _, result = await self._try_and_report(url, FetcherType.STEALTH, max_chars=max_chars)
        if doc:
            return doc, result

        if allow_escalation:
            esc_doc, esc_result = await self._try_escalation(url, max_chars=max_chars)
            if esc_doc:
                return esc_doc, esc_result

        return doc, result

    def _report_feedback(
        self: FetchEngine,
        url: str,
        fetcher_type: FetcherType,
        success: bool,
        latency_ms: float | None = None,
        cpu: float | None = None,
        memory: float | None = None,
    ) -> None:
        """Report fetch result to router (with multi-dimensional resource cost)."""
        self._router.report_result(url, fetcher_type, success, latency_ms, cpu, memory)
