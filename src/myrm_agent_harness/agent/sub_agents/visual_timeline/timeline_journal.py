"""Activity timeline journal and multi-dimensional query store (Item 61).

[INPUT]
- TimelineNode instances representing atomic code/file mutations and actions.
- TimelineFilterCriteria for multi-dimensional querying.

[OUTPUT]
- Chronologically indexed timeline event logs per session.
- Filtered timeline slices by actor, role, file path, operation, and timestamp.

[POS]
- Core logging and query repository for Tutti-style visual timeline tracking.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict

from .types import TimelineFilterCriteria, TimelineNode

logger = logging.getLogger(__name__)


class TimelineJournal:
    """Thread-safe event journal tracking multi-human multi-agent activity nodes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # session_id -> list of TimelineNode
        self._nodes_by_session: dict[str, list[TimelineNode]] = defaultdict(list)
        # node_id -> TimelineNode
        self._node_lookup: dict[str, TimelineNode] = {}
        # file_path -> list of node_id
        self._file_indices: dict[str, list[str]] = defaultdict(list)

    def record_node(self, node: TimelineNode) -> None:
        """Append an atomic activity event to the chronological timeline."""
        with self._lock:
            self._nodes_by_session[node.session_id].append(node)
            self._node_lookup[node.node_id] = node
            if node.file_path:
                self._file_indices[node.file_path].append(node.node_id)
            logger.debug(
                "Recorded timeline node %s by %s (%s) on %s",
                node.node_id,
                node.actor_name,
                node.actor_type.value,
                node.file_path,
            )

    def get_node(self, node_id: str) -> TimelineNode | None:
        """Retrieve an individual timeline node by unique ID."""
        with self._lock:
            return self._node_lookup.get(node_id)

    def get_file_history(self, file_path: str) -> list[TimelineNode]:
        """Retrieve the sequence of changes specifically targeting a given file."""
        with self._lock:
            node_ids = self._file_indices.get(file_path, [])
            return [self._node_lookup[nid] for nid in node_ids if nid in self._node_lookup]

    def query_nodes(
        self,
        session_id: str,
        criteria: TimelineFilterCriteria | None = None,
    ) -> list[TimelineNode]:
        """Perform multi-dimensional querying across the session's activity timeline."""
        with self._lock:
            nodes = self._nodes_by_session.get(session_id, [])
            if not criteria:
                return list(nodes)

            results: list[TimelineNode] = []
            for n in nodes:
                if criteria.actor_id and n.actor_id != criteria.actor_id:
                    continue
                if criteria.actor_type and n.actor_type != criteria.actor_type:
                    continue
                if criteria.file_path and n.file_path != criteria.file_path:
                    continue
                if criteria.operation_type and n.operation_type != criteria.operation_type:
                    continue
                if criteria.start_time is not None and n.timestamp < criteria.start_time:
                    continue
                if criteria.end_time is not None and n.timestamp > criteria.end_time:
                    continue
                results.append(n)

            return results

    def clear(self) -> None:
        """Clear all stored timeline nodes."""
        with self._lock:
            self._nodes_by_session.clear()
            self._node_lookup.clear()
            self._file_indices.clear()
