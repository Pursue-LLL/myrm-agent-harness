"""Hash-based incremental monitor.

Detects any content change by comparing normalized content hashes.
Best for summaries where line-level set diff is not reliable.

[INPUT]
- (none)

[OUTPUT]
- HashMonitor: Monitor based on full-content hash comparison.
- InvalidJsonLikeMonitorOutputError: Contract error for JSON-like invalid outputs.

[POS]
Hash-based incremental monitor.
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


class InvalidJsonLikeMonitorOutputError(ValueError):
    """Raised when monitor output looks like JSON but is invalid JSON text."""


class HashMonitor:
    """Monitor based on full-content hash comparison.

    Input format: arbitrary text output.
    Algorithm: SHA-256(normalized_output) vs last_hash.
    Output: full current_output when changed, empty string when unchanged.
    """

    def __init__(self, last_hash: str | None = None, ttl_days: int = 30) -> None:
        """Initialize with optional historical hash.

        Args:
            last_hash: Hash from previous successful run. None means baseline.
            ttl_days: TTL for automatic expiration (managed externally).
        """
        del ttl_days  # TTL is enforced by IncrementalMonitorManager.
        self._last_hash = last_hash
        self._is_baseline = last_hash is None
        self._last_current_hash: str | None = None

    def is_baseline(self) -> bool:
        """Check if this is the first run (no historical baseline)."""
        return self._is_baseline

    def compute_delta(self, current_output: str) -> str:
        """Return full output only when normalized content hash changes."""
        normalized = _normalize_for_hash(current_output)
        current_hash = hashlib.sha256(normalized.encode()).hexdigest()
        self._last_current_hash = current_hash

        if self._is_baseline:
            logger.info("HashMonitor: baseline run established (no delta output)")
            return ""

        if current_hash == self._last_hash:
            logger.debug("HashMonitor: no content change detected")
            return ""

        logger.info("HashMonitor: content change detected")
        return current_output

    def update_baseline(self, delta: str) -> None:
        """Persist the latest computed hash after successful processing."""
        del delta  # Hash monitor baseline update does not depend on delta text.
        if not self._last_current_hash:
            return
        self._last_hash = self._last_current_hash
        self._is_baseline = False

    def get_state_data(self) -> dict[str, object]:
        """Export monitor state for persistence."""
        return {
            "last_hash": self._last_hash,
            "is_baseline": self._is_baseline,
        }

    @classmethod
    def from_state_data(cls, data: dict[str, object], ttl_days: int = 30) -> HashMonitor:
        """Restore monitor from persisted state data."""
        last_hash = data.get("last_hash")
        if last_hash is not None and not isinstance(last_hash, str):
            logger.warning("Invalid last_hash data type, resetting to baseline")
            last_hash = None

        is_baseline = bool(data.get("is_baseline", False))
        monitor = cls(last_hash=last_hash if not is_baseline else None, ttl_days=ttl_days)
        if is_baseline:
            monitor._is_baseline = True
            monitor._last_hash = None
        return monitor


def _normalize_for_hash(current_output: str) -> str:
    """Normalize text for stable hashing.

    Strategy:
    1) Strip outer whitespace
    2) If the output is JSON, canonicalize key order and spacing
    3) For JSON arrays of dicts with ``asset`` keys and no order-sensitive
       keys (rank/position/index/order/sequence), sort by ``asset`` to reduce
       false positives from non-semantic ordering drift.
    4) For JSON-like but invalid payloads, raise contract error so upper
       layers can surface a user-visible signal instead of silent gating.
    """
    stripped = current_output.strip()
    if not stripped:
        return ""

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        if stripped.startswith("{") or stripped.startswith("["):
            logger.warning("HashMonitor: invalid JSON-like output detected")
            raise InvalidJsonLikeMonitorOutputError("invalid JSON-like monitor output")
        return stripped

    canonical = _canonicalize_json(parsed)
    return json.dumps(canonical, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonicalize_json(value: object) -> object:
    if isinstance(value, dict):
        return {k: _canonicalize_json(v) for k, v in value.items()}

    if isinstance(value, list):
        normalized_items = [_canonicalize_json(item) for item in value]
        if _is_sortable_asset_dict_list(normalized_items):
            asset_items: list[dict[str, object]] = [item for item in normalized_items if isinstance(item, dict)]
            return sorted(
                asset_items,
                key=lambda item: (
                    str(item.get("asset", "")).strip().upper(),
                    json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                ),
            )
        return normalized_items

    return value


_ORDER_SENSITIVE_KEYS = {"rank", "position", "index", "order", "sequence"}


def _is_sortable_asset_dict_list(items: list[object]) -> bool:
    if not items:
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        asset = item.get("asset")
        if not isinstance(asset, str) or not asset.strip():
            return False
        if any(str(key).lower() in _ORDER_SENSITIVE_KEYS for key in item):
            return False
    return True
