from __future__ import annotations

import contextlib
import time
from pathlib import Path

from myrm_agent_harness.agent.context_guard.types import ContextGuardConfig
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)


class EphemeralTransientSweeper:
    """Housekeeping sweeper for stale ephemeral spillover files."""

    def __init__(self, config: ContextGuardConfig | None = None) -> None:
        self.config = config or ContextGuardConfig()

    def sweep_directory(self, base_dir: Path | str) -> int:
        """Scan base_dir's spillover folder and remove files older than TTL (24 hours).

        Prevents sensitive plaintext leakage and unbounded disk growth.
        """
        root_path = Path(base_dir).expanduser().resolve()
        spillover_dir = root_path / self.config.spillover_dir_name
        if not spillover_dir.exists() or not spillover_dir.is_dir():
            return 0

        now = time.time()
        ttl = self.config.spillover_ttl_seconds
        removed_count = 0

        for item in spillover_dir.glob("*.md"):
            try:
                # Anti-symlink defense: avoid traversing external link targets
                if item.is_symlink():
                    item.unlink(missing_ok=True)
                    removed_count += 1
                    continue

                stat = item.stat()
                age = now - stat.st_mtime
                if age > ttl:
                    item.unlink(missing_ok=True)
                    removed_count += 1
                    logger.debug("Cleaned up expired transient file: %s (age=%.1fs)", item.name, age)
            except OSError as e:
                logger.warning("Failed to clean transient file %s: %s", item, e)

        # Clean leftover temporary writing artifacts (.tmp_*)
        for tmp_item in spillover_dir.glob(".tmp_*"):
            with contextlib.suppress(OSError):
                tmp_item.unlink(missing_ok=True)

        if removed_count > 0:
            logger.info("EphemeralTransientSweeper purged %d stale spillover files from %s", removed_count, spillover_dir)

        return removed_count
