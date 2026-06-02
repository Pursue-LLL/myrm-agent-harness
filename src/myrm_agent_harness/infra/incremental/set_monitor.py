"""Set-based incremental monitor.

Detects new items in line-delimited output by computing set difference.
Covers 80% of monitoring use cases: RSS feeds, URL lists, file listings, etc.

[INPUT]
- (none)

[OUTPUT]
- SetMonitor: Monitor based on set difference of line-delimited items.

[POS]
Set-based incremental monitor.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class SetMonitor:
    """Monitor based on set difference of line-delimited items.

    Input format: one item per line (URL, ID, hash, etc.)
    Algorithm: current_set - seen_set
    Output: only new items, one per line

    Example:
        >>> monitor = SetMonitor(seen={"url1", "url2"})
        >>> output = "url1\\nurl2\\nurl3\\nurl4"
        >>> delta = monitor.compute_delta(output)
        >>> delta
        'url3\\nurl4'
    """

    def __init__(self, seen: set[str] | None = None, ttl_days: int = 30) -> None:
        """Initialize with optional historical seen set.

        Args:
            seen: Set of previously seen items. None means first run (baseline).
            ttl_days: TTL for automatic expiration (not enforced here, used by manager).
        """
        self._seen = seen if seen is not None else set()
        self._ttl_days = ttl_days
        self._is_baseline = seen is None
        self._last_current: set[str] = set()

    def is_baseline(self) -> bool:
        """Check if this is the first run (no historical baseline)."""
        return self._is_baseline

    def compute_delta(self, current_output: str) -> str:
        """Compute new items by set difference.

        Args:
            current_output: Line-delimited items (one per line).

        Returns:
            Line-delimited new items, or empty string if no new items.
        """
        if not current_output.strip():
            return ""

        current_items = {line.strip() for line in current_output.splitlines() if line.strip()}

        self._last_current = current_items

        if self._is_baseline:
            logger.info(
                "SetMonitor: baseline run, found %d items (no delta output)",
                len(current_items),
            )
            return ""

        new_items = current_items - self._seen

        if new_items:
            logger.info(
                "SetMonitor: detected %d new items (total seen: %d)",
                len(new_items),
                len(self._seen),
            )
        else:
            logger.debug(
                "SetMonitor: no new items (total seen: %d)",
                len(self._seen),
            )

        return "\n".join(sorted(new_items))

    def update_baseline(self, delta: str) -> None:
        """Update seen set with new items from delta.

        Args:
            delta: Line-delimited new items (output from compute_delta).

        Note:
            For baseline runs, delta is empty but we need to update seen set
            with items from the last compute_delta call.
        """
        if self._is_baseline:
            self._seen.update(self._last_current)
            self._is_baseline = False
            logger.debug(
                "SetMonitor: baseline established, total seen: %d",
                len(self._seen),
            )
            return

        if not delta.strip():
            return

        new_items = {line.strip() for line in delta.splitlines() if line.strip()}
        self._seen.update(new_items)

        logger.debug(
            "SetMonitor: baseline updated, total seen: %d",
            len(self._seen),
        )

    def get_state_data(self) -> dict[str, object]:
        """Export internal state for persistence.

        Returns:
            Dict containing seen set and metadata.
        """
        return {
            "seen": sorted(self._seen),
            "is_baseline": self._is_baseline,
        }

    @classmethod
    def from_state_data(cls, data: dict[str, object], ttl_days: int = 30) -> SetMonitor:
        """Restore monitor from persisted state.

        Args:
            data: State dict from get_state_data().
            ttl_days: TTL configuration.

        Returns:
            Restored SetMonitor instance.
        """
        seen_list = data.get("seen", [])
        if not isinstance(seen_list, list):
            logger.warning("Invalid seen data type, resetting to empty set")
            seen_list = []

        seen_set = set(str(item) for item in seen_list)
        is_baseline = bool(data.get("is_baseline", False))

        monitor = cls(seen=seen_set if not is_baseline else None, ttl_days=ttl_days)
        if is_baseline:
            monitor._is_baseline = True
        return monitor
