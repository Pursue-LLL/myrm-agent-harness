"""Local folder watcher trigger for cron jobs.

Monitors configured directories for file system changes and dispatches
system events to the cron scheduler, enabling RPA-style automation:
"new file arrives → trigger agent task → process & notify".

Uses watchdog (already a harness dependency) for cross-platform FS monitoring.
Only active for local/desktop deployments (not cloud-hosted sandboxes).

[INPUT]
- watchdog (POS: File system events monitoring)

[OUTPUT]
- FolderWatchConfig: Configuration for a single folder watch rule.
- FolderWatchService: Background service managing multiple folder watchers.

[POS]
Local folder watcher trigger for cron scheduled tasks.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable, Coroutine

from watchdog.events import (
    FileCreatedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FolderWatchConfig:
    """Configuration for a folder watch rule.

    Attributes:
        path: Absolute path to the directory to monitor.
        patterns: Glob patterns to match (e.g. ["*.pdf", "*.docx"]).
            Empty means match all files.
        recursive: Whether to watch subdirectories.
        events: Which events to trigger on (create, modify, move).
        debounce_seconds: Minimum interval between dispatches for same file.
    """

    path: str
    patterns: tuple[str, ...] = ()
    recursive: bool = False
    events: tuple[str, ...] = ("create",)
    debounce_seconds: float = 5.0


EventDispatcher = Callable[[str, str, dict[str, object]], Coroutine[None, None, int]]


class _FolderEventHandler(FileSystemEventHandler):
    """Translates watchdog events into cron system event dispatches."""

    def __init__(
        self,
        config: FolderWatchConfig,
        dispatch_fn: EventDispatcher,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        super().__init__()
        self._config = config
        self._dispatch_fn = dispatch_fn
        self._loop = loop
        self._last_dispatch: dict[str, float] = {}

    def _matches_patterns(self, path: str) -> bool:
        if not self._config.patterns:
            return True
        name = Path(path).name
        return any(fnmatch(name, pat) for pat in self._config.patterns)

    def _matches_event_type(self, event: FileSystemEvent) -> bool:
        if isinstance(event, FileCreatedEvent) and "create" in self._config.events:
            return True
        if isinstance(event, FileModifiedEvent) and "modify" in self._config.events:
            return True
        if isinstance(event, FileMovedEvent) and "move" in self._config.events:
            return True
        return False

    def _should_dispatch(self, path: str) -> bool:
        now = time.time()
        last = self._last_dispatch.get(path, 0.0)
        if now - last < self._config.debounce_seconds:
            return False
        self._last_dispatch[path] = now
        return True

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        src_path = str(event.src_path)
        if not self._matches_event_type(event):
            return
        if not self._matches_patterns(src_path):
            return
        if not self._should_dispatch(src_path):
            return

        event_type = "file_created"
        if isinstance(event, FileModifiedEvent):
            event_type = "file_modified"
        elif isinstance(event, FileMovedEvent):
            event_type = "file_moved"

        payload: dict[str, object] = {
            "file_path": src_path,
            "file_name": Path(src_path).name,
            "watch_dir": self._config.path,
            "event_type": event_type,
        }

        asyncio.run_coroutine_threadsafe(
            self._dispatch_fn("folder_watcher", event_type, payload),
            self._loop,
        )
        logger.info(
            "Folder watcher dispatched: %s → %s",
            event_type,
            Path(src_path).name,
        )


class FolderWatchService:
    """Manages multiple folder watchers, dispatching events to cron scheduler.

    Usage:
        service = FolderWatchService(dispatch_fn=scheduler.dispatch_system_event)
        service.add_watch(FolderWatchConfig(path="/Users/me/Downloads", patterns=("*.pdf",)))
        service.start()
        # ... later ...
        service.stop()
    """

    def __init__(self, dispatch_fn: EventDispatcher) -> None:
        self._dispatch_fn = dispatch_fn
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._configs: list[FolderWatchConfig] = []
        self._started = False

    def add_watch(self, config: FolderWatchConfig) -> bool:
        """Add a folder watch configuration. Returns False if path doesn't exist."""
        path = Path(config.path)
        if not path.is_dir():
            logger.warning("Folder watcher: path does not exist: %s", config.path)
            return False
        self._configs.append(config)
        if self._started and self._observer:
            self._schedule_watch(config)
        return True

    def remove_watch(self, path: str) -> None:
        """Remove a watch by path. Requires restart to take effect."""
        self._configs = [c for c in self._configs if c.path != path]

    def start(self) -> None:
        """Start all configured watchers in a background thread."""
        if self._started:
            return
        if not self._configs:
            logger.debug("Folder watcher: no watches configured, skipping start")
            return

        self._observer = Observer()
        self._observer.daemon = True

        for config in self._configs:
            self._schedule_watch(config)

        self._observer.start()
        self._started = True
        logger.info(
            "Folder watcher started: monitoring %d path(s)",
            len(self._configs),
        )

    def _schedule_watch(self, config: FolderWatchConfig) -> None:
        if not self._observer:
            return
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                threading.Thread(target=self._loop.run_forever, daemon=True).start()

        handler = _FolderEventHandler(config, self._dispatch_fn, self._loop)
        self._observer.schedule(handler, config.path, recursive=config.recursive)

    def stop(self) -> None:
        """Stop all watchers."""
        if self._observer and self._started:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._started = False
            logger.info("Folder watcher stopped")

    @property
    def is_running(self) -> bool:
        return self._started

    @property
    def watch_count(self) -> int:
        return len(self._configs)
