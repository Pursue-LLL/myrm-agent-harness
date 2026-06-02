"""Recording manager for browser debugging features.

Unified management for trace, HAR, and profiler recording.


[INPUT]
- patchright.async_api::BrowserContext (POS: Playwright browser context)
- patchright.async_api::Page (POS: Playwright page instance)

[OUTPUT]
- RecordingState: Recording state for trace/HAR
- FileManager: File management with auto-cleanup
- RecordingManager: Unified recording lifecycle management

[POS]
Unified browser recording manager. Provides lifecycle management and file management
for trace and HAR recordings. Each recording type is independently managed; file operations are centralized.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)


@dataclass
class RecordingState:
    """Recording state for a specific recording type.

    Attributes:
        active: Whether recording is currently active
        output_path: Path to the output file (set when stopped)
        start_time: When recording started
    """

    active: bool = False
    output_path: Path | None = None
    start_time: datetime | None = None


class FileManager:
    """File management with auto-cleanup for recordings.

    Manages file storage and automatic cleanup of old files.
    """

    def __init__(self, base_dir: Path, max_files: int = 10) -> None:
        """Initialize file manager.

        Args:
            base_dir: Base directory for storing files
            max_files: Maximum number of files to keep (oldest deleted first)
        """
        self._base_dir = base_dir
        self._max_files = max_files
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def generate_filename(self, prefix: str, extension: str) -> Path:
        """Generate timestamped filename.

        Args:
            prefix: Filename prefix (e.g., "trace", "har")
            extension: File extension (e.g., "zip", "har")

        Returns:
            Full path to the new file
        """
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{prefix}-{timestamp}.{extension}"
        return self._base_dir / filename

    def cleanup_old_files(self, pattern: str) -> None:
        """Delete old files matching pattern, keeping only max_files.

        Args:
            pattern: Glob pattern (e.g., "trace-*.zip")
        """
        try:
            files = sorted(self._base_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

            if len(files) > self._max_files:
                for old_file in files[self._max_files :]:
                    try:
                        old_file.unlink()
                        logger.info(f"Deleted old recording: {old_file.name}")
                    except Exception as e:
                        logger.warning(f"Failed to delete {old_file}: {e}")
        except Exception as e:
            logger.warning(f"Failed to cleanup files with pattern {pattern}: {e}")


class RecordingManager:
    """Unified recording manager for trace and HAR.

    Manages lifecycle and file storage for Playwright trace and HAR recordings.
    """

    def __init__(self, base_dir: Path | None = None, max_files: int = 10) -> None:
        """Initialize recording manager.

        Args:
            base_dir: Base directory for recordings (default: ~/.cursor/browser-logs)
            max_files: Maximum number of files to keep per type
        """
        if base_dir is None:
            base_dir = Path.home() / ".cursor" / "browser-logs"

        self._file_manager = FileManager(base_dir, max_files)
        self._trace_state = RecordingState()
        self._har_state = RecordingState()

    async def start_trace(
        self,
        context: BrowserContext,
        screenshots: bool = True,
        snapshots: bool = True,
    ) -> str:
        """Start Playwright trace recording.

        Args:
            context: Browser context to trace
            screenshots: Include screenshots in trace
            snapshots: Include DOM snapshots in trace

        Returns:
            Success message

        Raises:
            RuntimeError: If trace is already active
        """
        if self._trace_state.active:
            raise RuntimeError("Trace recording is already active. Stop it first with trace_stop.")

        try:
            await context.tracing.start(screenshots=screenshots, snapshots=snapshots, sources=True)
            self._trace_state.active = True
            self._trace_state.start_time = datetime.now()
            logger.info("Trace recording started")
            return "Trace recording started successfully"
        except Exception as e:
            logger.error(f"Failed to start trace: {e}")
            raise RuntimeError(f"Failed to start trace recording: {e}") from e

    async def stop_trace(self, context: BrowserContext) -> Path:
        """Stop Playwright trace recording and save to file.

        Args:
            context: Browser context being traced

        Returns:
            Path to the saved trace file

        Raises:
            RuntimeError: If trace is not active
        """
        if not self._trace_state.active:
            raise RuntimeError("No active trace recording. Start it first with trace_start.")

        try:
            output_path = self._file_manager.generate_filename("trace", "zip")
            await context.tracing.stop(path=str(output_path))

            self._trace_state.active = False
            self._trace_state.output_path = output_path

            # Cleanup old files
            self._file_manager.cleanup_old_files("trace-*.zip")

            duration = (
                (datetime.now() - self._trace_state.start_time).total_seconds() if self._trace_state.start_time else 0
            )
            logger.info(f"Trace recording stopped: {output_path.name} (duration: {duration:.1f}s)")

            return output_path
        except Exception as e:
            self._trace_state.active = False
            logger.error(f"Failed to stop trace: {e}")
            raise RuntimeError(f"Failed to stop trace recording: {e}") from e

    async def start_har(
        self,
        page: Page,
        path: Path | None = None,
    ) -> str:
        """Start HAR (HTTP Archive) recording.

        Args:
            page: Page to record network traffic
            path: Optional explicit path (if None, auto-generated)

        Returns:
            Success message

        Raises:
            RuntimeError: If HAR recording is already active
        """
        if self._har_state.active:
            raise RuntimeError("HAR recording is already active. Stop it first with har_stop.")

        try:
            if path is None:
                path = self._file_manager.generate_filename("har", "har")

            # Start HAR recording using Playwright's route-based approach
            await page.route_from_har(str(path), update=True)

            self._har_state.active = True
            self._har_state.output_path = path
            self._har_state.start_time = datetime.now()

            logger.info(f"HAR recording started: {path.name}")
            return f"HAR recording started successfully: {path.name}"
        except Exception as e:
            logger.error(f"Failed to start HAR recording: {e}")
            raise RuntimeError(f"Failed to start HAR recording: {e}") from e

    async def stop_har(self, page: Page) -> Path:
        """Stop HAR recording.

        Args:
            page: Page being recorded

        Returns:
            Path to the saved HAR file

        Raises:
            RuntimeError: If HAR recording is not active
        """
        if not self._har_state.active:
            raise RuntimeError("No active HAR recording. Start it first with har_start.")

        try:
            # Unroute to finalize HAR file
            await page.unroute_all(behavior="wait")

            output_path = self._har_state.output_path
            self._har_state.active = False

            # Cleanup old files
            self._file_manager.cleanup_old_files("har-*.har")

            duration = (
                (datetime.now() - self._har_state.start_time).total_seconds() if self._har_state.start_time else 0
            )
            logger.info(f"HAR recording stopped: {output_path.name} (duration: {duration:.1f}s)")

            return output_path
        except Exception as e:
            self._har_state.active = False
            logger.error(f"Failed to stop HAR recording: {e}")
            raise RuntimeError(f"Failed to stop HAR recording: {e}") from e

    @property
    def trace_active(self) -> bool:
        """Whether trace recording is active."""
        return self._trace_state.active

    @property
    def har_active(self) -> bool:
        """Whether HAR recording is active."""
        return self._har_state.active

    @property
    def trace_output_path(self) -> Path | None:
        """Path to the last saved trace file."""
        return self._trace_state.output_path

    @property
    def har_output_path(self) -> Path | None:
        """Path to the last saved HAR file."""
        return self._har_state.output_path

    def get_status(self) -> dict[str, object]:
        """Get current recording status.

        Returns:
            Dictionary with status of all recording types
        """
        return {
            "trace": {
                "active": self._trace_state.active,
                "output_path": str(self._trace_state.output_path) if self._trace_state.output_path else None,
                "start_time": self._trace_state.start_time.isoformat() if self._trace_state.start_time else None,
            },
            "har": {
                "active": self._har_state.active,
                "output_path": str(self._har_state.output_path) if self._har_state.output_path else None,
                "start_time": self._har_state.start_time.isoformat() if self._har_state.start_time else None,
            },
        }
