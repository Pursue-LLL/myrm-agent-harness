"""Metrics cardinality control with dynamic label strategy.

Prevents metrics explosion by limiting high-cardinality labels.

[INPUT]

[OUTPUT]
- DynamicLabelManager: 动态标签管理器

[POS]
Metrics cardinality control. Maintains an LRU cache for high-frequency entities and aggregates low-frequency ones as 'other'.

"""

from __future__ import annotations

import threading
from collections import OrderedDict


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
