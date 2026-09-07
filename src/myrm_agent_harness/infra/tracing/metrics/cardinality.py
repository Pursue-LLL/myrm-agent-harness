"""Metrics cardinality control with dynamic label strategy.

Prevents metrics explosion by limiting high-cardinality labels.

[INPUT]

[OUTPUT]
- DynamicLabelManager: 动态标签管理器
- sanitize_metric_labels: 指标高基数防爆防火墙清洗函数
- HIGH_CARDINALITY_LABEL_BLOCKLIST: 阻断的高散列维度名单

[POS]
Metrics cardinality control. Maintains an LRU cache for high-frequency entities,
aggregates low-frequency ones as 'other', and strips unbounded high-cardinality keys.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

# High-cardinality label keys that must NEVER become metric dimensions.
# These keys have unbounded cardinality (e.g. UUIDs, filesystem paths, hashes).
# They belong in distributed Trace Spans and log contexts, NOT metric time series.
HIGH_CARDINALITY_LABEL_BLOCKLIST: frozenset[str] = frozenset({
    "session_id",
    "turn_id",
    "conversation_id",
    "user_id",
    "trace_id",
    "span_id",
    "request_id",
    "workspace",
    "workspace_dir",
    "tool_call_id",
    "filepath",
    "file_path",
    "command",
})


def sanitize_metric_labels(
    labels: Mapping[str, Any] | None,
    drop_blocklist: bool = True,
    max_label_length: int = 128,
) -> dict[str, str]:
    """Sanitize and protect metric attributes against cardinality explosion.

    1. Filters out unbounded high-cardinality identifiers (e.g. session_id, workspace).
    2. Coerces non-string values to bounded strings.
    3. Truncates overly long label values.

    Args:
        labels: Raw label mapping passed by caller.
        drop_blocklist: Whether to strip known high-cardinality keys. Defaults to True.
        max_label_length: Maximum allowed string length for any label value.

    Returns:
        Cleaned, bounded dictionary of string labels.
    """
    if not labels:
        return {}

    sanitized: dict[str, str] = {}
    stripped_keys: list[str] = []

    for key, value in labels.items():
        if value is None:
            continue

        normalized_key = str(key).strip().lower()
        if drop_blocklist and normalized_key in HIGH_CARDINALITY_LABEL_BLOCKLIST:
            stripped_keys.append(str(key))
            continue

        str_val = str(value)
        if len(str_val) > max_label_length:
            str_val = str_val[:max_label_length]
        sanitized[str(key)] = str_val

    if stripped_keys and logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "[CardinalityFirewall] Stripped high-cardinality label(s) from metric: %s",
            stripped_keys,
        )

    return sanitized


class DynamicLabelManager:
    """Dynamic label manager for metrics cardinality control.

    Features:
    - High-frequency tracking: Maintains LRU cache of top entities
    - Dynamic aggregation: Low-frequency entities aggregated as 'other'
    - Thread-safe: Can be used from multiple threads
    - Memory bounded: Fixed maximum cache size

    Attributes:
        max_tracked: Maximum number of tracked entities (default: 10)
        access_threshold: Minimum accesses to be tracked (default: 2)
    """

    def __init__(
        self,
        max_tracked: int = 10,
        access_threshold: int = 2,
    ) -> None:
        self.max_tracked = max_tracked
        self.access_threshold = access_threshold
        self._access_counts: OrderedDict[str, int] = OrderedDict()
        self._tracked_entities: set[str] = set()
        self._lock = threading.Lock()

    def get_label_value(self, entity: str) -> str:
        """Get label value for entity (entity or 'other').

        Args:
            entity: Entity identifier

        Returns:
            Label value (entity if tracked, 'other' otherwise)
        """
        with self._lock:
            # Increment access count
            current_count = self._access_counts.get(entity, 0)
            self._access_counts[entity] = current_count + 1
            self._access_counts.move_to_end(entity)

            # Check if already tracked
            if entity in self._tracked_entities:
                return entity

            # Check if should be tracked
            if current_count + 1 >= self.access_threshold:
                # Check if we have space
                if len(self._tracked_entities) < self.max_tracked:
                    self._tracked_entities.add(entity)
                    return entity

                # Check if more frequent than least frequent tracked entity
                min_tracked_entity = self._find_least_frequent_tracked()
                if min_tracked_entity:
                    min_count = self._access_counts[min_tracked_entity]
                    if current_count + 1 > min_count:
                        # Replace least frequent
                        self._tracked_entities.remove(min_tracked_entity)
                        self._tracked_entities.add(entity)
                        return entity

            # Not tracked: return 'other'
            return "other"

    def _find_least_frequent_tracked(self) -> str | None:
        """Find least frequently accessed tracked entity.

        Returns:
            Entity identifier or None if no tracked entities
        """
        if not self._tracked_entities:
            return None

        min_entity = None
        min_count = float("inf")

        for entity in self._tracked_entities:
            count = self._access_counts.get(entity, 0)
            if count < min_count:
                min_count = count
                min_entity = entity

        return min_entity

    def clear(self) -> None:
        """Clear all tracking data (for testing)."""
        with self._lock:
            self._access_counts.clear()
            self._tracked_entities.clear()

    def get_tracked_entities(self) -> set[str]:
        """Get currently tracked entities (for testing).

        Returns:
            Set of tracked entity identifiers
        """
        with self._lock:
            return self._tracked_entities.copy()
