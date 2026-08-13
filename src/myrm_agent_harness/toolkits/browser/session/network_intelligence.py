"""CDP-based network intelligence for on-demand response body retrieval.

[INPUT]
- patchright.async_api::Page (POS: Playwright page instance)
- patchright.async_api::CDPSession (POS: Chrome DevTools Protocol session)

[OUTPUT]
- NetworkIntelligence: CDP-based lazy response body retrieval and request replay

[POS]
Provides Agent-accessible API intelligence layer that captures requestIds via CDP
Network domain events and offers on-demand response body retrieval using
Network.getResponseBody. Cooperates with NetworkLogger (which handles synchronous
metadata) — this component handles asynchronous CDP body queries.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.redact import redact_sensitive_text

if TYPE_CHECKING:
    from patchright.async_api import CDPSession, Page

logger = logging.getLogger(__name__)

_MAX_TRACKED_REQUESTS = 100
_BODY_PREVIEW_MAX_CHARS = 8000
# Redaction window before truncation: keeps a credential crossing a truncation
# boundary structurally intact long enough to be masked (aligned with
# NetworkLogger's preview-window design).
_RAW_PREVIEW_WINDOW = 4096
_BODY_RAW_WINDOW = 16384


@dataclass(frozen=True, slots=True)
class CdpRequestRecord:
    """Tracked CDP request with requestId for lazy body retrieval.

    Attributes:
        request_id: CDP-assigned request identifier for getResponseBody
        url: Request URL
        method: HTTP method
        resource_type: Network resource type (XHR, Fetch, Document, etc.)
        status: HTTP response status code
        mime_type: Response MIME type
        post_data: Raw POST body window (for replay and GraphQL identification; display-time redaction in get_summary)
        timestamp: Request time (monotonic)
    """

    request_id: str
    url: str
    method: str
    resource_type: str
    status: int | None = None
    mime_type: str | None = None
    post_data: str | None = None
    timestamp: float = 0.0


class NetworkIntelligence:
    """CDP-based network intelligence for lazy response body retrieval.

    Unlike NetworkLogger (synchronous Playwright event callbacks for metadata),
    this component uses CDP Network domain to track requestIds and provides
    on-demand response body access via Network.getResponseBody.

    Memory model: Only stores requestId + metadata (~200 bytes per request).
    Response bodies are fetched lazily from Chrome's internal cache on demand,
    consuming zero additional memory until explicitly requested.
    """

    def __init__(self, max_requests: int = _MAX_TRACKED_REQUESTS) -> None:
        self._requests: deque[CdpRequestRecord] = deque(maxlen=max_requests)
        self._cdp_session: CDPSession | None = None
        self._bound_page: Page | None = None
        self._enabled = False

    @property
    def is_enabled(self) -> bool:
        """Whether CDP Network monitoring is active."""
        return self._enabled

    async def attach(self, page: Page) -> None:
        """Attach CDP Network monitoring to a page.

        Idempotent: re-attaching to the same page is a no-op.
        Attaching to a different page detaches from the previous one first.
        """
        if self._bound_page is page and self._enabled:
            return

        await self.detach()

        try:
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Network.enable")

            cdp.on("Network.requestWillBeSent", self._on_request_will_be_sent)
            cdp.on("Network.responseReceived", self._on_response_received)

            self._cdp_session = cdp
            self._bound_page = page
            self._enabled = True
        except Exception as exc:
            logger.warning("NetworkIntelligence: attach failed (non-critical): %s", exc)
            self._enabled = False

    async def detach(self) -> None:
        """Detach CDP monitoring and release resources."""
        if self._cdp_session is not None:
            with contextlib.suppress(Exception):
                await self._cdp_session.detach()
            self._cdp_session = None
        self._bound_page = None
        self._enabled = False

    def _on_request_will_be_sent(self, params: dict) -> None:
        """Handle CDP Network.requestWillBeSent event."""
        try:
            request = params.get("request", {})
            resource_type = params.get("type", "")

            if resource_type not in ("XHR", "Fetch", "Document"):
                return

            request_id = params.get("requestId", "")
            if not request_id:
                return

            post_data_raw = request.get("postData", "")
            # Keep the raw window for replay: network_replay re-sends the real
            # body, so it must not be redacted here. Display-time redaction
            # happens in get_summary.
            post_data_original = (
                post_data_raw[:_RAW_PREVIEW_WINDOW] if post_data_raw else None
            )

            record = CdpRequestRecord(
                request_id=request_id,
                url=request.get("url", ""),
                method=request.get("method", "GET"),
                resource_type=resource_type,
                post_data=post_data_original,
                timestamp=time.time(),
            )
            self._requests.append(record)
        except Exception as exc:
            logger.debug(
                "NetworkIntelligence: requestWillBeSent handler error: %s", exc
            )

    def _on_response_received(self, params: dict) -> None:
        """Handle CDP Network.responseReceived — update status and mime_type."""
        try:
            request_id = params.get("requestId", "")
            response = params.get("response", {})
            status = response.get("status")
            mime_type = response.get("mimeType", "")

            for i in range(len(self._requests) - 1, -1, -1):
                if self._requests[i].request_id == request_id:
                    old = self._requests[i]
                    self._requests[i] = CdpRequestRecord(
                        request_id=old.request_id,
                        url=old.url,
                        method=old.method,
                        resource_type=old.resource_type,
                        status=status,
                        mime_type=mime_type,
                        post_data=old.post_data,
                        timestamp=old.timestamp,
                    )
                    break
        except Exception as exc:
            logger.debug("NetworkIntelligence: responseReceived handler error: %s", exc)

    def get_api_requests(self) -> list[CdpRequestRecord]:
        """Get all tracked XHR/Fetch requests (most recent last)."""
        return [r for r in self._requests if r.resource_type in ("XHR", "Fetch")]

    async def get_response_body(self, index: int) -> str:
        """Get response body for a tracked request by index (1-based).

        Uses CDP Network.getResponseBody for lazy retrieval from Chrome's cache.
        Returns truncated body if it exceeds max chars to prevent token explosion.

        Args:
            index: 1-based index from the API requests list

        Returns:
            Response body text or error message
        """
        if self._cdp_session is None:
            return "Error: CDP session not available. Navigate to a page first."

        api_requests = self.get_api_requests()
        if index < 1 or index > len(api_requests):
            return f"Error: Invalid index {index}. Valid range: 1-{len(api_requests)}"

        record = api_requests[index - 1]

        try:
            result = await self._cdp_session.send(
                "Network.getResponseBody",
                {"requestId": record.request_id},
            )
            body = result.get("body", "")
            is_base64 = result.get("base64Encoded", False)

            if is_base64:
                return f"[Binary response, {len(body)} base64 chars] MIME: {record.mime_type or 'unknown'}"

            if len(body) > _BODY_PREVIEW_MAX_CHARS:
                return (
                    f"{redact_sensitive_text(body[: _BODY_RAW_WINDOW])[:_BODY_PREVIEW_MAX_CHARS]}\n\n"
                    f"... [truncated, total {len(body)} chars] "
                    f"MIME: {record.mime_type or 'unknown'}"
                )
            return body

        except Exception as exc:
            error_msg = str(exc)
            if "No resource with given identifier found" in error_msg:
                return (
                    f"Error: Response body no longer available for request #{index} "
                    f"({record.method} {record.url}). "
                    "This happens when the page has navigated away. "
                    "Bodies are only available for the current page's requests."
                )
            return f"Error retrieving response body: {error_msg}"

    def get_summary(self) -> str:
        """Get formatted summary of tracked API requests for Agent display."""
        api_requests = self.get_api_requests()
        if not api_requests:
            return ""

        lines: list[str] = []
        for i, req in enumerate(api_requests, 1):
            status_str = str(req.status) if req.status else "pending"
            line = f"  {i}. {req.method} {req.url} [{status_str}]"
            if req.post_data:
                # Redact the raw stored body before display so credentials never
                # reach the Agent via network_log.
                safe_post = redact_sensitive_text(req.post_data)[:200]
                line += f"\n     POST: {safe_post}"
            lines.append(line)

        return "\n".join(lines)

    def clear(self) -> None:
        """Clear all tracked requests."""
        self._requests.clear()
