"""Skill usage statistics and lifecycle state collector.

Tracks skill usage patterns and lifecycle state for the curator / forgetting
mechanism.  Statistics are stored in {skill_dir}/.stats.json for lightweight
persistence.

[INPUT]
- backends.skills.types::SkillUsageStats (POS: Skill system core data types.)
- backends.skills.types::SkillLifecycleStatus (POS: Skill system core data types.)
- infra.atomic_write::atomic_write (POS: Crash-consistent file write.)

[OUTPUT]
- SkillStatsCollector: Collects and persists skill usage statistics and
  lifecycle state (lifecycle_status, pinned).

[POS]
Skill usage statistics and lifecycle state collector.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from time import time

from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillUsageStats
from myrm_agent_harness.infra.atomic_write import atomic_write

logger = logging.getLogger(__name__)

_STATS_FILENAME = ".stats.json"
_CORRUPT_SUFFIX = ".corrupt"
_BATCH_FLUSH_INTERVAL_SEC = 60


class SkillStatsCollector:
    """Collects and persists skill usage statistics and lifecycle state.

    Design:
    - Async write with 60s batch flush (performance optimisation)
    - Per-skill stats stored in {skill_dir}/.stats.json, written atomically so a crash never leaves a torn file
    - A ledger that cannot be parsed is set aside as ``.stats.json.corrupt``; one that cannot be read is never
      replaced by a blank one
    - No database dependency (aligns with framework design principles)
    - Lifecycle state (lifecycle_status, pinned) co-located with usage data
    """

    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root.resolve()
        self._pending_updates: dict[str, SkillUsageStats] = {}
        self._last_flush_time: float = time()

    # ── Usage recording ─────────────────────────────────────────────

    def record_use(self, skill_path: Path, *, success: bool | None) -> None:
        """Record one run that used the skill.

        ``success`` is the observed outcome of the run's tool calls, or ``None`` when no outcome was
        observable (the skill was only loaded, or several loaded skills made the owner ambiguous).
        A use always counts; only an observed outcome moves the success/failure counters.

        If the skill is currently ``stale``, it is auto-recovered to
        ``active`` (inspired by Hermes' stale-reactivation design).

        Args:
            skill_path: Absolute path to skill directory
            success: Observed outcome of the run, None when unobservable
        """
        stats = self._ensure_loaded(skill_path)
        stats.call_count += 1
        if success is True:
            stats.success_count += 1
        elif success is False:
            stats.failure_count += 1
        now = datetime.now(UTC)
        stats.last_used_at = now
        stats.append_usage(timestamp=now.isoformat(), success=success)

        if stats.lifecycle_status == SkillLifecycleStatus.STALE:
            stats.lifecycle_status = SkillLifecycleStatus.ACTIVE
            logger.info("Skill %s auto-recovered from stale to active on usage", skill_path.name)

        if time() - self._last_flush_time > _BATCH_FLUSH_INTERVAL_SEC:
            self.flush()

    # ── Lifecycle management ────────────────────────────────────────

    def update_lifecycle_status(
        self,
        skill_path: Path,
        status: SkillLifecycleStatus,
    ) -> None:
        """Set the lifecycle status for a skill and flush immediately.

        Args:
            skill_path: Absolute path to skill directory
            status: Target lifecycle status
        """
        stats = self._ensure_loaded(skill_path)
        stats.lifecycle_status = status
        self._write_stats(skill_path, stats)

    def set_pinned(self, skill_path: Path, *, pinned: bool) -> None:
        """Pin or unpin a skill and flush immediately.

        Args:
            skill_path: Absolute path to skill directory
            pinned: True to pin (exempt from curator), False to unpin
        """
        stats = self._ensure_loaded(skill_path)
        stats.pinned = pinned
        self._write_stats(skill_path, stats)

    def reset_usage(self, skill_path: Path) -> None:
        """Discard the verdict on past runs and flush immediately.

        Clears the run counters and history so the success rate starts a fresh window
        (e.g. after the skill was fixed). Lifecycle state, pin, provenance and ``last_used_at`` are
        kept: resetting must neither revive an archived skill nor make an idle one look unused.

        Args:
            skill_path: Absolute path to skill directory
        """
        stats = self._ensure_loaded(skill_path)
        stats.call_count = 0
        stats.success_count = 0
        stats.failure_count = 0
        stats.usage_history.clear()
        self._write_stats(skill_path, stats)

    # ── Persistence ─────────────────────────────────────────────────

    def flush(self) -> None:
        """Persist all pending statistics to disk."""
        for skill_path_str, stats in self._pending_updates.items():
            self._write_stats(Path(skill_path_str), stats)

        self._pending_updates.clear()
        self._last_flush_time = time()
        logger.debug("Flushed skill usage stats")

    def get_stats(self, skill_path: Path) -> SkillUsageStats:
        """Get current statistics for a skill (including pending updates).

        A ledger that cannot be read right now yields an unsaved blank view instead of failing the caller.
        """
        skill_key = str(skill_path)

        if skill_key in self._pending_updates:
            return self._pending_updates[skill_key]

        try:
            return self._load_stats(skill_path)
        except OSError as e:
            logger.warning("Failed to read stats for skill %s: %s", skill_path.name, e)
            return SkillUsageStats(created_at=datetime.now(UTC))

    # ── Internal helpers ────────────────────────────────────────────

    def _ensure_loaded(self, skill_path: Path) -> SkillUsageStats:
        """Return cached stats or load from disk."""
        skill_key = str(skill_path)
        if skill_key not in self._pending_updates:
            self._pending_updates[skill_key] = self._load_stats(skill_path)
        return self._pending_updates[skill_key]

    def _load_stats(self, skill_path: Path) -> SkillUsageStats:
        """Load existing stats from disk. Sets created_at on first encounter.

        Raises:
            OSError: The ledger exists but cannot be read; the caller must not replace it with a blank one.
        """
        stats_file = skill_path / _STATS_FILENAME

        try:
            data = json.loads(stats_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self._new_stats(skill_path)
        except ValueError:  # JSONDecodeError and UnicodeDecodeError
            data = None

        if not isinstance(data, dict):
            self._set_aside_corrupt(stats_file)
            return self._new_stats(skill_path)

        stats = SkillUsageStats.from_dict(data)
        if stats.created_at is None:
            stats.created_at = datetime.now(UTC)
        return stats

    def _new_stats(self, skill_path: Path) -> SkillUsageStats:
        stats = SkillUsageStats(created_at=datetime.now(UTC))
        self._write_stats(skill_path, stats)
        return stats

    @staticmethod
    def _set_aside_corrupt(stats_file: Path) -> None:
        """Keep an unparseable ledger next to the new one so it can still be inspected."""
        aside = stats_file.with_name(stats_file.name + _CORRUPT_SUFFIX)
        logger.warning(
            "Stats file %s is unreadable; keeping it as %s and starting a new ledger", stats_file, aside.name
        )
        with contextlib.suppress(OSError):
            os.replace(stats_file, aside)

    def _write_stats(self, skill_path: Path, stats: SkillUsageStats) -> None:
        """Atomically write stats for a single skill; a skill directory that is gone is left gone."""
        if not skill_path.is_dir():
            logger.debug("Skill directory %s no longer exists; stats not written", skill_path)
            return
        try:
            atomic_write(skill_path / _STATS_FILENAME, json.dumps(stats.to_dict(), indent=2))
        except Exception as e:
            logger.warning(
                "Failed to write stats for skill %s: %s",
                skill_path.name,
                e,
            )
