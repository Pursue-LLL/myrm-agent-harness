"""Cross-surface agent activity ingress bridge coordinator.

Maintains bounded recent projection and active presence states for external surfaces
including Tauri desktop, CLI tooling, and remote office clones.

[INPUT]
- __future__
- collections
- threading
- time
- types

[OUTPUT]
- CrossSurfaceActivityBridge

[POS]
Cross-surface agent activity ingress bridge coordinator.
"""

from __future__ import annotations

import collections
import threading
import time
from collections.abc import Sequence

from .types import (
    CrossSurfaceProjectionSnapshot,
    IngressActivityItem,
    PresenceStatus,
    SurfacePresenceSummary,
)


class CrossSurfaceActivityBridge:
    """Thread-safe coordinator for cross-surface activity ingress and presence projection."""

    def __init__(self, chat_id: str, max_recent_items: int = 50) -> None:
        self.chat_id: str = chat_id
        self._max_recent_items: int = max(10, max_recent_items)
        self._lock: threading.Lock = threading.Lock()

        self._recent_activities: collections.deque[IngressActivityItem] = collections.deque(
            maxlen=self._max_recent_items
        )
        self._presences: dict[str, SurfacePresenceSummary] = {}
        self._total_ingressed: int = 0
        self._last_ingressed_at: float | None = None

    def ingest_activity(self, item: IngressActivityItem) -> CrossSurfaceProjectionSnapshot:
        """Ingests a single external activity event into the bounded projection buffer."""
        with self._lock:
            bounded_item = self._bound_item_locked(item)
            self._recent_activities.append(bounded_item)
            self._total_ingressed += 1
            self._last_ingressed_at = bounded_item.timestamp
            self._update_presence_locked(bounded_item)
            return self._build_snapshot_locked()

    def ingest_batch(
        self, items: Sequence[IngressActivityItem]
    ) -> CrossSurfaceProjectionSnapshot:
        """Ingests a sequence of external activity events atomically."""
        with self._lock:
            for item in items:
                bounded_item = self._bound_item_locked(item)
                self._recent_activities.append(bounded_item)
                self._total_ingressed += 1
                self._last_ingressed_at = bounded_item.timestamp
                self._update_presence_locked(bounded_item)
            return self._build_snapshot_locked()

    def prune_stale_presences(self, max_idle_seconds: float = 300.0) -> int:
        """Marks presences idle or removes completed ones exceeding max_idle_seconds."""
        now = time.time()
        pruned_count = 0
        with self._lock:
            for session_key, summary in list(self._presences.items()):
                idle_duration = now - summary.last_active_at
                if idle_duration > max_idle_seconds:
                    if summary.status == "completed":
                        del self._presences[session_key]
                        pruned_count += 1
                    elif summary.status == "active":
                        summary.status = "idle"
                        pruned_count += 1
        return pruned_count

    def get_snapshot(self) -> CrossSurfaceProjectionSnapshot:
        """Returns the current bounded projection snapshot."""
        with self._lock:
            return self._build_snapshot_locked()

    def reset(self) -> None:
        """Resets the bridge state and cleared all projected events."""
        with self._lock:
            self._recent_activities.clear()
            self._presences.clear()
            self._total_ingressed = 0
            self._last_ingressed_at = None

    def _bound_item_locked(self, item: IngressActivityItem) -> IngressActivityItem:
        if len(item.preview_text) <= 256:
            return item
        truncated = item.preview_text[:253] + "..."
        return IngressActivityItem(
            activity_id=item.activity_id,
            session_key=item.session_key,
            source_surface=item.source_surface,
            agent_id=item.agent_id,
            activity_kind=item.activity_kind,
            preview_text=truncated,
            metadata=item.metadata,
            timestamp=item.timestamp,
        )

    def _update_presence_locked(self, item: IngressActivityItem) -> None:
        new_status: PresenceStatus = "active"
        if item.activity_kind == "turn_complete":
            new_status = "completed"

        if item.session_key in self._presences:
            pres = self._presences[item.session_key]
            pres.agent_id = item.agent_id
            pres.source_surface = item.source_surface
            pres.status = new_status
            pres.last_active_at = item.timestamp
            pres.recent_activities_count += 1
        else:
            self._presences[item.session_key] = SurfacePresenceSummary(
                session_key=item.session_key,
                source_surface=item.source_surface,
                agent_id=item.agent_id,
                status=new_status,
                last_active_at=item.timestamp,
                recent_activities_count=1,
            )

    def _build_snapshot_locked(self) -> CrossSurfaceProjectionSnapshot:
        presences_list = sorted(
            self._presences.values(),
            key=lambda p: p.last_active_at,
            reverse=True,
        )
        return CrossSurfaceProjectionSnapshot(
            chat_id=self.chat_id,
            active_presences=list(presences_list),
            total_ingressed_activities=self._total_ingressed,
            bounded_recent_activities=list(self._recent_activities),
            last_ingressed_at=self._last_ingressed_at,
        )
