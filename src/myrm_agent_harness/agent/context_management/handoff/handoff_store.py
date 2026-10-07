"""Persistent storage backend for agent handoff packets.

Guarantees durable on-disk persistence (JSON format) and synchronized in-memory caching.
Protects concurrent read/write operations with reentrant mutexes.
Strict typing applied: No `Any` types allowed.

[INPUT]
- agent.context_management.handoff.types::AgentHandoffSpec, HandoffStatus (POS: Type definitions for
  cross-agent/cross-session typed handoff protocol.)

[OUTPUT]
- AgentHandoffStore: Thread-safe and durable store for agent handoffs.

[POS]
Persistent storage backend for agent handoff packets.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

from myrm_agent_harness.agent.context_management.handoff.types import (
    AgentHandoffSpec,
    HandoffStatus,
)

logger = logging.getLogger(__name__)


class AgentHandoffStore:
    """Thread-safe and durable store for agent handoffs."""

    def __init__(self, storage_dir: Path | str | None = None) -> None:
        if storage_dir is not None:
            self.storage_dir: Path | None = Path(storage_dir)
            self.storage_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.storage_dir = None

        self._lock = threading.RLock()
        self._cache: dict[str, AgentHandoffSpec] = {}
        if self.storage_dir is not None:
            self._load_from_disk()

    def _load_from_disk(self) -> None:
        """Hydrate in-memory index from disk files upon startup."""
        if self.storage_dir is None or not self.storage_dir.exists():
            return
        for file_path in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                spec = AgentHandoffSpec.model_validate(data)
                self._cache[spec.handoff_id] = spec
            except Exception as exc:
                logger.warning("Failed to deserialize handoff at %s: %s", file_path, exc)

    def save(self, spec: AgentHandoffSpec) -> Path | None:
        """Durable write of handoff specification to cache and disk."""
        with self._lock:
            self._cache[spec.handoff_id] = spec
            if self.storage_dir is not None:
                target_file = self.storage_dir / f"{spec.handoff_id}.json"
                raw = json.dumps(spec.model_dump(mode="json"), indent=2, ensure_ascii=False)
                target_file.write_text(raw, encoding="utf-8")
                return target_file
            return None

    def get(self, handoff_id: str) -> AgentHandoffSpec | None:
        """Fetch handoff specification by unique ID."""
        with self._lock:
            return self._cache.get(handoff_id)

    def list_pending(self, target_profile_id: str | None = None) -> list[AgentHandoffSpec]:
        """List all unassigned or matching pending handoff memorandums."""
        with self._lock:
            results: list[AgentHandoffSpec] = []
            for spec in self._cache.values():
                if spec.status != HandoffStatus.PENDING:
                    continue
                # Target profile match: None matches any; otherwise exact match or unassigned
                if target_profile_id is None or spec.target_profile_id is None or spec.target_profile_id == target_profile_id:
                    results.append(spec)
            # Sort chronologically descending
            results.sort(key=lambda s: s.created_at, reverse=True)
            return results

    def list_by_session(self, session_id: str) -> list[AgentHandoffSpec]:
        """List all handoffs initiated by or claimed by a specific session."""
        with self._lock:
            results = [
                s
                for s in self._cache.values()
                if s.session_id == session_id or s.claimed_by_session_id == session_id
            ]
            results.sort(key=lambda s: s.created_at, reverse=True)
            return results

    def update_status(
        self,
        handoff_id: str,
        new_status: HandoffStatus,
        claimed_by_profile_id: str | None = None,
        claimed_by_session_id: str | None = None,
    ) -> bool:
        """Update handoff status and persist mutations atomically."""
        with self._lock:
            spec = self._cache.get(handoff_id)
            if spec is None:
                return False

            now = time.time()
            updated_data = spec.model_dump()
            updated_data["status"] = new_status
            if new_status == HandoffStatus.CLAIMED:
                updated_data["claimed_at"] = now
                updated_data["claimed_by_profile_id"] = claimed_by_profile_id
                updated_data["claimed_by_session_id"] = claimed_by_session_id
            elif new_status == HandoffStatus.COMPLETED:
                updated_data["completed_at"] = now

            new_spec = AgentHandoffSpec.model_validate(updated_data)
            self._cache[handoff_id] = new_spec

            if self.storage_dir is not None:
                target_file = self.storage_dir / f"{handoff_id}.json"
                raw = json.dumps(new_spec.model_dump(mode="json"), indent=2, ensure_ascii=False)
                target_file.write_text(raw, encoding="utf-8")

            return True
