"""Skill usage statistics and lifecycle state collector.

Tracks skill usage patterns and lifecycle state for the curator / forgetting
mechanism.  Statistics are stored in {skill_dir}/.stats.json for lightweight
persistence.

[INPUT]
- backends.skills.types::SkillUsageStats (POS: Skill system core data types.)
- backends.skills.types::SkillLifecycleStatus (POS: Skill system core data types.)

[OUTPUT]
- SkillStatsCollector: Collects and persists skill usage statistics and
  lifecycle state (lifecycle_status, pinned).

[POS]
Skill usage statistics and lifecycle state collector.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import time

from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillUsageStats

logger = logging.getLogger(__name__)

_STATS_FILENAME = ".stats.json"
_BATCH_FLUSH_INTERVAL_SEC = 60


class SkillStatsCollector:
    """Collects and persists skill usage statistics and lifecycle state.

    Design:
    - Async write with 60s batch flush (performance optimisation)
    - Per-skill stats stored in {skill_dir}/.stats.json
    - No database dependency (aligns with framework design principles)
    - Lifecycle state (lifecycle_status, pinned) co-located with usage data
    """

    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root.resolve()
        self._pending_updates: dict[str, SkillUsageStats] = {}
        self._last_flush_time: float = time()

    # ── Usage recording ─────────────────────────────────────────────

    def record_usage(
        self,
        skill_path: Path,
        success: bool,
        duration_ms: float,
    ) -> None:
        """Record a skill usage event.

        If the skill is currently ``stale``, it is auto-recovered to
        ``active`` (inspired by Hermes' stale-reactivation design).

        Args:
            skill_path: Absolute path to skill directory
            success: Whether the invocation succeeded
            duration_ms: Execution duration in milliseconds
        """
        skill_key = str(skill_path)

        if skill_key not in self._pending_updates:
            self._pending_updates[skill_key] = self._load_stats(skill_path)

        stats = self._pending_updates[skill_key]
        stats.call_count += 1
        if success:
            stats.success_count += 1
        else:
            stats.failure_count += 1
        now = datetime.now(UTC)
        stats.last_used_at = now
        stats.total_duration_ms += duration_ms
        stats.append_usage(timestamp=now.isoformat(), success=success, duration_ms=duration_ms)

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

    # ── Persistence ─────────────────────────────────────────────────

    def flush(self) -> None:
        """Persist all pending statistics to disk."""
        for skill_path_str, stats in self._pending_updates.items():
            self._write_stats(Path(skill_path_str), stats)

        self._pending_updates.clear()
        self._last_flush_time = time()
        logger.debug("Flushed skill usage stats")

    def get_stats(self, skill_path: Path) -> SkillUsageStats:
        """Get current statistics for a skill (including pending updates)."""
        skill_key = str(skill_path)

        if skill_key in self._pending_updates:
            return self._pending_updates[skill_key]

        return self._load_stats(skill_path)

    # ── Internal helpers ────────────────────────────────────────────

    def _ensure_loaded(self, skill_path: Path) -> SkillUsageStats:
        """Return cached stats or load from disk."""
        skill_key = str(skill_path)
        if skill_key not in self._pending_updates:
            self._pending_updates[skill_key] = self._load_stats(skill_path)
        return self._pending_updates[skill_key]

    def _load_stats(self, skill_path: Path) -> SkillUsageStats:
        """Load existing stats from disk. Sets created_at on first encounter."""
        stats_file = skill_path / _STATS_FILENAME

        if not stats_file.exists():
            stats = SkillUsageStats(created_at=datetime.now(UTC))
            self._write_stats(skill_path, stats)
            return stats

        try:
            data = json.loads(stats_file.read_text())
            stats = SkillUsageStats.from_dict(data)
            if stats.created_at is None:
                stats.created_at = datetime.now(UTC)
            return stats
        except Exception as e:
            logger.warning(
                "Failed to load stats for skill %s: %s",
                skill_path.name,
                e,
            )
            return SkillUsageStats(created_at=datetime.now(UTC))

    def _write_stats(self, skill_path: Path, stats: SkillUsageStats) -> None:
        """Write stats to disk for a single skill."""
        stats_file = skill_path / _STATS_FILENAME
        try:
            stats_file.write_text(json.dumps(stats.to_dict(), indent=2))
        except Exception as e:
            logger.warning(
                "Failed to write stats for skill %s: %s",
                skill_path.name,
                e,
            )
