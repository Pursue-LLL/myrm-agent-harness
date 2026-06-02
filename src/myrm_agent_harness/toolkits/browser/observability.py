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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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


class BrowserObservability:
    """Browser observability manager.

    Manages recording lifecycle, progress notifications, and checkpoint metrics for browser sessions.
    Minimal implementation following the principle of progressive enhancement.
    """

    def __init__(
        self,
        recording_config: RecordingConfig,
        progress_callback: ProgressCallback | None = None,
        checkpoint_metrics: CheckpointMetrics | None = None,
    ) -> None:
        """Initialize observability manager.

        Args:
            recording_config: Recording configuration
            progress_callback: Optional callback for progress notifications
            checkpoint_metrics: Optional checkpoint metrics instance (for shared tracking)
        """
        self._config = recording_config
        self._progress_callback = progress_callback
        self._video_path: Path | None = None
        self._task_succeeded: bool = True
        self._checkpoint_metrics = checkpoint_metrics

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
            message: Progress message (e.g., "正在第 2/5 步: 填写表单")
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

        return stats
