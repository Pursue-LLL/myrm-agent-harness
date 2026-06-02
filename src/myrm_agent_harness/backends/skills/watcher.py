"""Skill Directory Watcher for Hot Reloading.

Monitors a directory for changes to SKILL.md files and automatically
updates the SQLiteSkillSnapshot.

[INPUT]
- watchdog (POS: File system events monitoring)
- snapshot::SQLiteSkillSnapshot (POS: Skill snapshot cache)

[OUTPUT]
- SkillWatcher: Background watcher for skill hot reloading

[POS]
Skill hot reload mechanism. Detects local file changes and triggers targeted snapshot updates.
"""

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from myrm_agent_harness.backends.skills.snapshot import SQLiteSkillSnapshot

logger = logging.getLogger(__name__)


class _SkillEventHandler(FileSystemEventHandler):
    """Handles file system events for SKILL.md files."""

    def __init__(self, snapshot: SQLiteSkillSnapshot, workspace_root: Path):
        self.snapshot = snapshot
        self.workspace_root = workspace_root
        self._debounce_timer: threading.Timer | None = None
        self._pending_paths: set[Path] = set()
        self._lock = threading.Lock()
        self._debounce_seconds = 0.5

    def _is_skill_md(self, path_str: str) -> bool:
        path = Path(path_str)
        return path.name == "SKILL.md" and not path.parent.name.startswith(".")

    def _process_pending(self) -> None:
        with self._lock:
            paths_to_process = self._pending_paths.copy()
            self._pending_paths.clear()

        for path in paths_to_process:
            if path.exists():
                self.snapshot.upsert_from_path(path, workspace_root=self.workspace_root)
            else:
                self.snapshot.delete_from_path(path)

    def _schedule_update(self, path: Path) -> None:
        with self._lock:
            self._pending_paths.add(path)
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self._debounce_seconds, self._process_pending)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_skill_md(event.src_path):
            self._schedule_update(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self._is_skill_md(event.src_path):
            self._schedule_update(Path(event.src_path))

    def on_deleted(self, event: FileSystemEvent) -> None:
        path = Path(event.src_path)
        if not event.is_directory and self._is_skill_md(event.src_path):
            self._schedule_update(path)
        elif event.is_directory and path.parent == self.workspace_root and not path.name.startswith("."):
            # If a whole skill directory is deleted, we must remove it from snapshot
            # We simulate a SKILL.md deletion
            self._schedule_update(path / "SKILL.md")

    def on_moved(self, event: FileSystemEvent) -> None:
        src_path = Path(event.src_path)
        dest_path = Path(event.dest_path)

        if not event.is_directory:
            if self._is_skill_md(event.src_path):
                self._schedule_update(src_path)
            if self._is_skill_md(event.dest_path):
                self._schedule_update(dest_path)
        else:
            # If a whole skill directory is renamed/moved
            if src_path.parent == self.workspace_root and not src_path.name.startswith("."):
                self._schedule_update(src_path / "SKILL.md")
            if dest_path.parent == self.workspace_root and not dest_path.name.startswith("."):
                self._schedule_update(dest_path / "SKILL.md")


class SkillWatcher:
    """Watches a directory for skill changes and updates the snapshot."""

    def __init__(self, watch_dir: Path | str, snapshot_path: Path | str | None = None):
        self.watch_dir = Path(watch_dir).resolve()
        if snapshot_path is None:
            self.snapshot_path = self.watch_dir / ".skills_snapshot.sqlite"
        else:
            self.snapshot_path = Path(snapshot_path).resolve()

        self.snapshot = SQLiteSkillSnapshot(self.snapshot_path)
        self.observer: Observer | None = None

    def start(self) -> None:
        """Start the background watcher."""
        if self.observer is not None:
            return

        if not self.watch_dir.exists():
            logger.warning(f"SkillWatcher: Directory {self.watch_dir} does not exist, not starting.")
            return

        event_handler = _SkillEventHandler(self.snapshot, workspace_root=self.watch_dir)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.watch_dir), recursive=True)
        self.observer.start()
        logger.info(f" SkillWatcher started monitoring: {self.watch_dir}")

    def stop(self) -> None:
        """Stop the background watcher."""
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None
            logger.info("SkillWatcher stopped.")
