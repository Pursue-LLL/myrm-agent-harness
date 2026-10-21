"""Browser inspector live view SSE mixin.

[INPUT]
- session.view_update_payload::capture_browser_view_update_data (POS: shared browser inspector payload builder)
- core.events.types::AgentEventType (POS: harness SSE event type registry)
- utils.runtime.progress_sink::get_tool_progress_sink (POS: per-turn tool SSE sink)

[OUTPUT]
- BrowserSessionViewMixin._publish_inspector_view: emit throttled browser_view_update SSE events

[POS]
Browser Live Co-View (BLCV) mixin for BrowserSession. Mirrors DesktopSession DESKTOP_VIEW_UPDATE.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.session.snapshot_result import SnapshotResult

logger = logging.getLogger(__name__)

_VIEW_EMIT_MIN_INTERVAL_S = 0.3


class BrowserSessionViewMixin:
    """Push browser_view_update SSE events for WebUI Browser Inspector."""

    _view_emit_last_monotonic: float

    async def _publish_inspector_view(
        self,
        *,
        snapshot_result: SnapshotResult | None = None,
        force: bool = False,
    ) -> None:
        """Emit browser_view_update when a progress sink is active (agent turn)."""
        now = time.monotonic()
        if not force and (now - self._view_emit_last_monotonic) < _VIEW_EMIT_MIN_INTERVAL_S:
            return

        from myrm_agent_harness.core.events.types import AgentEventType
        from myrm_agent_harness.toolkits.browser.session.view_update_payload import (
            capture_browser_view_update_data,
        )
        from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

        sink = get_tool_progress_sink()
        if sink is None:
            return

        try:
            await self._ensure_components()
            data = await capture_browser_view_update_data(self, snapshot_result=snapshot_result)
        except Exception:
            logger.debug("Browser inspector view capture failed", exc_info=True)
            return

        self._view_emit_last_monotonic = time.monotonic()
        await sink.emit(
            {
                "type": AgentEventType.BROWSER_VIEW_UPDATE.value,
                "data": data,
            }
        )
