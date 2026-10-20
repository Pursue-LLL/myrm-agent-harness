"""In-memory session delta registry and conflict reconciliation.

[INPUT]
.models::DeltaCategory, DeltaConsolidationPlan, EphemeralMemoryDelta (POS: domain models)
typing::Sequence, collections::defaultdict, threading::Lock (POS: concurrency-safe typing)

[OUTPUT]
EphemeralDeltaRegistry: thread-safe registry tracking, formatting, and batch-consolidating deltas.

[POS]
Harness framework layer engine for Item 98.
Stores in-flight corrections without touching frozen System Prompt.
Strict typing applied: No `any` types allowed. Single file < 400 lines.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime
from uuid import uuid4

from myrm_agent_harness.agent.middlewares.memory_context.ephemeral_delta.models import (
    DeltaCategory,
    DeltaConsolidationPlan,
    EphemeralMemoryDelta,
)


class EphemeralDeltaRegistry:
    """Thread-safe registry for session-scoped in-flight deltas with conflict healing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # session_id -> list of deltas
        self._registry: dict[str, list[EphemeralMemoryDelta]] = defaultdict(list)

    def record_delta(
        self,
        session_id: str,
        key: str,
        value: str,
        *,
        category: DeltaCategory = DeltaCategory.CORRECTION,
        raw_instruction: str = "",
        turn_index: int = 1,
    ) -> EphemeralMemoryDelta:
        """Record an in-flight ephemeral delta with automatic key deduplication and conflict healing."""
        delta = EphemeralMemoryDelta(
            delta_id=f"delta_{uuid4().hex[:10]}",
            session_id=session_id,
            category=category,
            key=key.strip(),
            value=value.strip(),
            raw_instruction=raw_instruction.strip(),
            turn_index=turn_index,
            created_at=datetime.now().astimezone(),
            is_consolidated=False,
        )

        with self._lock:
            existing = self._registry[session_id]
            # Replace previous in-flight delta for the same key to preserve recency
            filtered = [d for d in existing if d.key.lower() != key.strip().lower()]
            filtered.append(delta)
            self._registry[session_id] = filtered

        return delta

    def get_active_deltas(self, session_id: str) -> list[EphemeralMemoryDelta]:
        """Fetch all active, unconsolidated deltas for a session."""
        with self._lock:
            deltas = self._registry.get(session_id, [])
            return [d for d in deltas if not d.is_consolidated]

    def format_human_tail_tag(self, session_id: str) -> str:
        """Format active deltas into a compact, zero-cache-break XML block for human message tail.

        This tag is appended to the tail of the final HumanMessage in the current turn,
        avoiding any prefix cache invalidation while ensuring immediate LLM recency override.
        """
        active_deltas = self.get_active_deltas(session_id)
        if not active_deltas:
            return ""

        lines: list[str] = [
            "<ephemeral_session_deltas>",
            "[Active Session Corrections - Highest Recency Priority]:",
        ]
        for d in active_deltas:
            lines.append(f"- {d.category.value}: {d.key} -> \"{d.value}\" (Turn {d.turn_index})")
        lines.append("</ephemeral_session_deltas>")
        return "\n".join(lines)

    def generate_consolidation_plan(self, session_id: str) -> DeltaConsolidationPlan:
        """Generate post-session batch consolidation plan to commit deltas into durable storage."""
        with self._lock:
            active_deltas = [d for d in self._registry.get(session_id, []) if not d.is_consolidated]

        superseded_keys = [d.key for d in active_deltas]
        target_tables = ["user_profile", "user_preferences", "project_constraints"]

        # Approximate saved recomputation tokens by preserving cache over N turns
        tokens_saved = len(active_deltas) * 120

        return DeltaConsolidationPlan(
            session_id=session_id,
            deltas_to_commit=active_deltas,
            superseded_keys=superseded_keys,
            target_storage_tables=target_tables,
            consolidation_timestamp=datetime.now().astimezone(),
            total_tokens_saved=tokens_saved,
        )

    def mark_consolidated(self, session_id: str) -> int:
        """Mark all deltas in session as consolidated after post-session persistence."""
        count = 0
        with self._lock:
            if session_id in self._registry:
                for d in self._registry[session_id]:
                    if not d.is_consolidated:
                        d.is_consolidated = True
                        count += 1
        return count

    def clear_session(self, session_id: str) -> None:
        """Clear session deltas entirely upon session destruction."""
        with self._lock:
            self._registry.pop(session_id, None)
