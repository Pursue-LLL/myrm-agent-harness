"""Playwright trace and HAR recording controls for BrowserSession.

[INPUT]
- (none)

[OUTPUT]
- BrowserSessionRecordingMixin: start_trace / stop_trace / start_har / stop_har / get_rec...

[POS]
Playwright trace and HAR recording controls for BrowserSession.
"""

from __future__ import annotations


class BrowserSessionRecordingMixin:
    """start_trace / stop_trace / start_har / stop_har / get_recording_status."""

    async def start_trace(self, screenshots: bool = True, snapshots: bool = True) -> str:
        """Start Playwright trace recording."""
        await self._ensure_components()
        if self._recording_manager is None:
            raise RuntimeError("RecordingManager not initialized. Recording not enabled.")

        page = self._tab_controller.get_active_page()
        context = page.context

        return await self._recording_manager.start_trace(context, screenshots, snapshots)

    async def stop_trace(self) -> str:
        """Stop Playwright trace recording and return file path."""
        await self._ensure_components()
        if self._recording_manager is None:
            raise RuntimeError("RecordingManager not initialized. Recording not enabled.")

        page = self._tab_controller.get_active_page()
        context = page.context

        output_path = await self._recording_manager.stop_trace(context)
        return f"Trace saved to: {output_path}"

    async def start_har(self) -> str:
        """Start HAR (HTTP Archive) recording."""
        await self._ensure_components()
        if self._recording_manager is None:
            raise RuntimeError("RecordingManager not initialized. Recording not enabled.")

        page = self._tab_controller.get_active_page()
        return await self._recording_manager.start_har(page)

    async def stop_har(self) -> str:
        """Stop HAR recording and return file path."""
        await self._ensure_components()
        if self._recording_manager is None:
            raise RuntimeError("RecordingManager not initialized. Recording not enabled.")

        page = self._tab_controller.get_active_page()
        output_path = await self._recording_manager.stop_har(page)
        return f"HAR saved to: {output_path}"

    def get_recording_status(self) -> dict[str, object]:
        """Get current recording status for trace and HAR."""
        if self._recording_manager is None:
            return {"trace": {"active": False}, "har": {"active": False}}
        return self._recording_manager.get_status()
