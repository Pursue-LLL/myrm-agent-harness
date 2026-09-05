"""Browser observability — recording, progress tracking, and checkpoint metrics.

Provides minimal observability for browser automation:
- Video recording (development mode or on-demand)
- Progress notifications
- Final screenshot capture
- Checkpoint metrics tracking (optional)


[INPUT]
- patchright.async_api::BrowserContext (POS: Playwright browser context)
- patchright.async_api::Page (POS: Playwright page instance)
- checkpoint.metrics::CheckpointMetrics (POS: checkpoint monitoring metrics)

[OUTPUT]
- RecordingConfig: Recording configuration (enabled, output_dir, retention_policy)
- ProgressCallback: Type alias for progress notification callback
- BrowserObservability: Manages recording lifecycle, progress tracking, and checkpoint metrics

[POS]
Observability module for the browser toolkit. Provides video recording, progress notifications, and checkpoint monitoring
for debugging and UX optimization. Follows a minimalist principle: records only in dev environment or on failure by default, avoiding over-engineering.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, Page, Request
    from .checkpoint.metrics import CheckpointMetrics

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class RecordingConfig:
    """Recording configuration for browser sessions.

    Attributes:
        enabled: Whether recording is enabled
        output_dir: Directory to save recordings (relative or absolute)
        save_on_success: Whether to keep recordings of successful tasks
        save_on_failure: Whether to keep recordings of failed tasks
        video_size: Video dimensions (width, height)
    """

    enabled: bool = False
    output_dir: str = "./videos"
    save_on_success: bool = False
    save_on_failure: bool = True
    video_size: tuple[int, int] = (1280, 720)


@dataclass
class BrowserRunTelemetry:
    """Telemetry capturing runtime compute duration, network usage, and session health."""

    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    active_compute_seconds: float = 0.0
    total_bytes_transferred: int = 0
    request_count: int = 0
    failed_request_count: int = 0
    page_count: int = 0
    watchdog_tripped_count: int = 0
    last_activity_time: float = field(default_factory=time.monotonic)

    @property
    def total_duration_seconds(self) -> float:
        """Total session duration from start until end or current time."""
        current = self.end_time if self.end_time is not None else time.time()
        return max(0.0, current - self.start_time)

    def record_activity(self) -> None:
        """Refresh active heartbeat timestamp."""
        self.last_activity_time = time.monotonic()

    def record_transfer(self, bytes_transferred: int) -> None:
        """Record transferred network bytes."""
        self.last_activity_time = time.monotonic()
        if bytes_transferred > 0:
            self.total_bytes_transferred += bytes_transferred

    def record_request(self, *, success: bool, bytes_transferred: int = 0) -> None:
        """Record completed or failed request and optional transferred bytes."""
        self.last_activity_time = time.monotonic()
        self.request_count += 1
        if not success:
            self.failed_request_count += 1
        if bytes_transferred > 0:
            self.total_bytes_transferred += bytes_transferred

    def record_compute(self, duration_seconds: float) -> None:
        """Record active compute/action execution duration."""
        self.last_activity_time = time.monotonic()
        if duration_seconds > 0:
            self.active_compute_seconds += duration_seconds

    def mark_closed(self) -> None:
        """Mark session end time."""
        if self.end_time is None:
            self.end_time = time.time()

    def snapshot(self) -> dict[str, object]:
        """Return point-in-time telemetry dictionary."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "active_compute_seconds": round(self.active_compute_seconds, 2),
            "total_bytes_transferred": self.total_bytes_transferred,
            "request_count": self.request_count,
            "failed_request_count": self.failed_request_count,
            "page_count": self.page_count,
            "watchdog_tripped_count": self.watchdog_tripped_count,
            "last_activity_time": self.last_activity_time,
        }


class BrowserObservability:
    """Browser observability manager.

    Manages recording lifecycle, progress notifications, runtime telemetry, and checkpoint metrics.
    Minimal implementation following the principle of progressive enhancement.
    """

    def __init__(
        self,
        recording_config: RecordingConfig,
        progress_callback: ProgressCallback | None = None,
        checkpoint_metrics: CheckpointMetrics | None = None,
        telemetry: BrowserRunTelemetry | None = None,
    ) -> None:
        """Initialize observability manager.

        Args:
            recording_config: Recording configuration
            progress_callback: Optional callback for progress notifications
            checkpoint_metrics: Optional checkpoint metrics instance (for shared tracking)
            telemetry: Optional existing BrowserRunTelemetry instance
        """
        self._config = recording_config
        self._progress_callback = progress_callback
        self._video_path: Path | None = None
        self._task_succeeded: bool = True
        self._checkpoint_metrics = checkpoint_metrics
        self._telemetry = telemetry if telemetry is not None else BrowserRunTelemetry()

    @property
    def telemetry(self) -> BrowserRunTelemetry:
        """Runtime compute and bandwidth telemetry."""
        return self._telemetry

    def attach_to_context(self, context: BrowserContext) -> None:
        """Attach lightweight observers to BrowserContext for real-time bandwidth and page telemetry."""
        def _on_page(_page: Page) -> None:
            self._telemetry.page_count += 1

        def _on_request_finished(request: Request) -> None:
            try:
                size = 0
                response = request.response()
                if response is not None:
                    headers = response.headers
                    cl = headers.get("content-length")
                    if cl and cl.isdigit():
                        size = int(cl)
                    elif headers.get("transfer-encoding", "").lower() == "chunked":
                        # Chunked response compensation
                        header_bytes = sum(len(k) + len(v) + 4 for k, v in headers.items())
                        size = max(header_bytes, 1024)
                if request.post_data:
                    size += len(request.post_data.encode("utf-8", errors="ignore"))
                self._telemetry.record_request(success=True, bytes_transferred=size)
            except Exception:
                self._telemetry.record_request(success=True, bytes_transferred=0)

        def _on_request_failed(_request: Request) -> None:
            self._telemetry.record_request(success=False, bytes_transferred=0)

        try:
            context.on("page", _on_page)
            context.on("requestfinished", _on_request_finished)
            context.on("requestfailed", _on_request_failed)
        except Exception as exc:
            logger.debug("Failed to attach browser context telemetry listeners: %s", exc)

    def check_action_watchdog(
        self,
        action_start_time: float,
        timeout_seconds: float = 180.0,
        activity_idle_threshold: float = 60.0,
    ) -> bool:
        """Check if single action compute duration exceeded safety watchdog threshold.

        Features active heartbeat awareness: if action exceeded total timeout (default 180s),
        it will only trip if the session has also been idle without any network/compute
        heartbeat activity for ``activity_idle_threshold`` (default 60s). This prevents
        killing legitimate heavy-throughput actions (e.g. streaming/large downloads)
        while firmly stopping hung infinite loops.

        Returns:
            True if within safe duration limits; False if tripped/hung.
        """
        now = time.monotonic()
        elapsed = now - action_start_time
        if elapsed > timeout_seconds:
            idle_time = now - self._telemetry.last_activity_time
            if idle_time > activity_idle_threshold:
                self._telemetry.watchdog_tripped_count += 1
                logger.warning(
                    "Browser action exceeded watchdog threshold (elapsed=%.1fs > %.1fs, idle=%.1fs > %.1fs); potential infinite loop detected",
                    elapsed,
                    timeout_seconds,
                    idle_time,
                    activity_idle_threshold,
                )
                return False
        return True

    @property
    def recording_enabled(self) -> bool:
        """Whether recording is currently enabled."""
        return self._config.enabled

    @property
    def video_path(self) -> Path | None:
        """Path to the recorded video file (if recording was enabled)."""
        return self._video_path

    def get_context_kwargs(self) -> dict[str, object]:
        """Get BrowserContext initialization kwargs for recording.

        Returns:
            Dictionary of kwargs to pass to browser.new_context()
        """
        if not self._config.enabled:
            return {}

        # Ensure output directory exists
        output_dir = Path(self._config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        return {
            "record_video_dir": str(output_dir),
            "record_video_size": {
                "width": self._config.video_size[0],
                "height": self._config.video_size[1],
            },
        }

    async def notify_progress(self, message: str) -> None:
        """Send progress notification to user.

        Args:
            message: Progress message (e.g., "Step 2/5: filling in the form")
        """
        if self._progress_callback:
            try:
                await self._progress_callback(message)
            except Exception as e:
                logger.warning("Progress callback failed: %s", e)

    def mark_task_status(self, success: bool) -> None:
        """Mark the task execution status.

        Args:
            success: Whether the task succeeded
        """
        self._task_succeeded = success

    def cleanup_recording(self, video_path: Path | None = None) -> None:
        """Clean up recording based on task status.

        Args:
            video_path: Explicit path to the recorded video file (recommended).
                       If None, attempts to find the most recent .webm file (deprecated, not safe for concurrent sessions).

        Should be called after the browser context is closed (when video file is written).
        """
        if not self._config.enabled:
            return

        if video_path is None:
            # Fallback: find most recent file (not safe for concurrent sessions)
            output_dir = Path(self._config.output_dir)
            if not output_dir.exists():
                return

            video_files = sorted(output_dir.glob("*.webm"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not video_files:
                logger.warning("Recording was enabled but no video file found in %s", output_dir)
                return
            video_path = video_files[0]

        self._video_path = video_path

        # Decision logic: keep or delete based on task status
        should_keep = (self._task_succeeded and self._config.save_on_success) or (
            not self._task_succeeded and self._config.save_on_failure
        )

        if should_keep:
            logger.info("Recording saved: %s (task_success=%s)", self._video_path, self._task_succeeded)
        else:
            try:
                self._video_path.unlink()
                logger.info("Recording deleted: %s (task_success=%s)", self._video_path, self._task_succeeded)
                self._video_path = None
            except Exception as e:
                logger.warning("Failed to delete recording %s: %s", self._video_path, e)

    @property
    def checkpoint_metrics(self) -> CheckpointMetrics | None:
        """Get checkpoint metrics (if enabled).

        Returns:
            CheckpointMetrics instance or None
        """
        return self._checkpoint_metrics

    def get_observability_stats(self) -> dict[str, object]:
        """Get comprehensive observability statistics.

        Returns:
            Dictionary with recording status and checkpoint metrics
        """
        stats: dict[str, object] = {
            "recording_enabled": self._config.enabled,
            "task_succeeded": self._task_succeeded,
        }

        if self._video_path:
            stats["video_path"] = str(self._video_path)

        if self._checkpoint_metrics:
            stats["checkpoint_metrics"] = self._checkpoint_metrics.to_dict()

        stats["telemetry"] = self._telemetry.snapshot()

        return stats
