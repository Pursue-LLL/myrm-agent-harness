"""Network request logger for Agent diagnostics.


[INPUT]
- patchright.async_api::Page (POS: Playwright page instance)
- patchright.async_api::Request (POS: Playwright request object)
- patchright.async_api::Response (POS: Playwright response object)

[OUTPUT]
- RequestInfo: Immutable request/response record
- NetworkLogger: Synchronous network request capture and formatting

[POS]
Network request logging for the browser toolkit. Provides self-diagnosis capability for browser session network activity.

"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from patchright.async_api import Page, Request, Response

logger = logging.getLogger(__name__)

_STATIC_RESOURCE_TYPES = frozenset({"image", "stylesheet", "font", "media"})


@dataclass(frozen=True, slots=True)
class RequestInfo:
    """Immutable record of a network request/response.

    Attributes:
        method: HTTP method (GET/POST/etc.)
        url: Request URL
        resource_type: Playwright resource type (document/xhr/fetch/etc.)
        timestamp: Request start time (unix timestamp)
        status: HTTP status code (None if request failed)
        status_text: HTTP status text (e.g., "OK", "Not Found")
        duration_ms: Request duration in milliseconds
        post_data_preview: First 200 chars of POST body (for GraphQL/API identification)
    """

    method: str
    url: str
    resource_type: str
    timestamp: float
    status: int | None = None
    status_text: str | None = None
    duration_ms: float | None = None
    post_data_preview: str | None = None

    @property
    def is_api_request(self) -> bool:
        """Whether this is an API request (XHR/Fetch)."""
        return self.resource_type in ("xhr", "fetch")

    @property
    def is_failed(self) -> bool:
        """Whether this request failed (4xx/5xx status)."""
        return self.status is not None and self.status >= 400


class NetworkLogger:
    """网络RequestFilter and Record，供 Agent 诊断。

    按资源TypeFilter，FIFO 限制条数；回调 in  Patchright 派发Page事件时SyncExecute。
     using  WeakKeyDictionary，以 Request  is KeyRecord待Match Start时间。

     not yet  using  ``__slots__``，so that Patchright 向监听Function挂接InternalProperty。
    """

    def __init__(self, max_requests: int = 50) -> None:
        """Initialize network logger.

        Args:
            max_requests: Maximum number of requests to store (FIFO)
        """
        self._requests: deque[RequestInfo] = deque(maxlen=max_requests)
        self._pending: WeakKeyDictionary[Request, float] = WeakKeyDictionary()
        self._bound_page: Page | None = None

    @property
    def bound_page(self) -> Page | None:
        """Current already Register监听  Page（ and 活跃 Tab 对齐，由 BrowserSession 驱动）。"""
        return self._bound_page

    def _cb_request(self, request: Request) -> None:
        self._on_request(request)

    def _cb_response(self, response: Response) -> None:
        self._on_response(response)

    def _cb_request_failed(self, request: Request) -> None:
        self._on_request_failed(request)

    def detach_page(self, page: Page) -> None:
        """from 指定 Page 移除监听；Only当该 Page  is Current绑定Object时生效。"""
        if self._bound_page is not page:
            return
        try:
            page.off("request", self._cb_request)
            page.off("response", self._cb_response)
            page.off("requestfailed", self._cb_request_failed)
        except Exception as exc:
            logger.warning("NetworkLogger: detach_page failed: %s", exc)
        finally:
            if self._bound_page is page:
                self._bound_page = None
            self._pending.clear()

    def detach_current(self) -> None:
        """移除Current绑定 Page 上 监听（若 no 绑定则 no-op）。"""
        if self._bound_page is not None:
            self.detach_page(self._bound_page)

    def start_capture(self, page: Page) -> None:
        """in  *page* 上Register网络监听； already 绑定Other Page 时会先 detach。

        对同一 ``page`` 重复Call is 幂 etc.（ not 重复Register）。

        Args:
            page: Patchright / Playwright Page Instance
        """
        if self._bound_page is page:
            return
        if self._bound_page is not None:
            self.detach_page(self._bound_page)
        self._bound_page = page
        page.on("request", self._cb_request)
        page.on("response", self._cb_response)
        page.on("requestfailed", self._cb_request_failed)

    def stop_capture(self) -> None:
        """卸下监听并清Empty pending；保留 already Complete队列 ``_requests``。"""
        self.detach_current()
        self._pending.clear()

    def _should_capture(self, resource_type: str) -> bool:
        """Whether to capture this resource type."""
        return resource_type not in _STATIC_RESOURCE_TYPES

    def _on_request(self, request: Request) -> None:
        """Handle request event."""
        try:
            if not self._should_capture(request.resource_type):
                return
            self._pending[request] = time.time()
        except Exception as exc:
            logger.warning("Failed to capture request: %s", exc)

    def _on_response(self, response: Response) -> None:
        """Handle response event."""
        try:
            request = response.request
            if request not in self._pending:
                return

            start_time = self._pending.pop(request)
            duration_ms = (time.time() - start_time) * 1000

            post_data_preview: str | None = None
            if request.method in ("POST", "PUT", "PATCH"):
                raw = request.post_data
                if raw:
                    post_data_preview = raw[:200]

            info = RequestInfo(
                method=request.method,
                url=request.url,
                resource_type=request.resource_type,
                timestamp=start_time,
                status=response.status,
                status_text=response.status_text,
                duration_ms=duration_ms,
                post_data_preview=post_data_preview,
            )
            self._requests.append(info)

        except Exception as exc:
            logger.warning("Failed to capture response: %s", exc)

    def _on_request_failed(self, request: Request) -> None:
        """Handle request failure event."""
        try:
            if request not in self._pending:
                return

            start_time = self._pending.pop(request)
            duration_ms = (time.time() - start_time) * 1000

            info = RequestInfo(
                method=request.method,
                url=request.url,
                resource_type=request.resource_type,
                timestamp=start_time,
                status=None,
                status_text="Request Failed",
                duration_ms=duration_ms,
            )
            self._requests.append(info)

        except Exception as exc:
            logger.warning("Failed to capture failed request: %s", exc)

    def get_summary(self, filter_mode: str = "api") -> str:
        """Get formatted summary of captured requests.

        Args:
            filter_mode: Filter mode
                - 'api': Only XHR/Fetch requests (default)
                - 'failed': Only 4xx/5xx errors
                - 'all': All captured requests

        Returns:
            Formatted string with request details
        """
        filtered = self._filter_requests(filter_mode)

        if not filtered:
            return f"No network requests captured (filter={filter_mode})."

        recent = filtered[-20:]

        lines = [f"Network Log ({len(filtered)} total, showing last {len(recent)}):"]
        for i, req in enumerate(recent, 1):
            lines.extend(self._format_request(req, i))

        return "\n".join(lines)

    def _format_request(self, req: RequestInfo, index: int) -> list[str]:
        """Format a single request for display.

        Args:
            req: Request info to format
            index: Display index number

        Returns:
            List of formatted lines for this request
        """
        parts = ["", f"{index}. {req.method} {req.url}"]

        if req.status is not None:
            status_marker = "OK" if req.status < 400 else "FAIL"
            parts.append(f"   [{status_marker}] Status: {req.status} {req.status_text or ''}")
        elif req.status_text:
            parts.append(f"   [FAIL] {req.status_text}")

        if req.duration_ms is not None:
            parts.append(f"   Duration: {req.duration_ms:.0f}ms")

        if req.post_data_preview:
            parts.append(f"   POST body: {req.post_data_preview}")

        return parts

    def _filter_requests(self, filter_mode: str) -> list[RequestInfo]:
        """Filter requests based on mode.

        Args:
            filter_mode: 'api', 'failed', or 'all'

        Returns:
            Filtered list of RequestInfo
        """
        match filter_mode:
            case "api":
                return [r for r in self._requests if r.is_api_request]
            case "failed":
                return [r for r in self._requests if r.is_failed]
            case "all":
                return list(self._requests)
            case _:
                logger.warning("Unknown filter mode: %s, defaulting to 'api'", filter_mode)
                return [r for r in self._requests if r.is_api_request]

    def clear(self) -> None:
        """Clear all captured requests and pending state."""
        self._requests.clear()
        self._pending.clear()

    def get_pending_count(self) -> int:
        """Get count of pending requests (for troubleshooting).

        Returns:
            Number of requests awaiting response
        """
        return len(self._pending)
