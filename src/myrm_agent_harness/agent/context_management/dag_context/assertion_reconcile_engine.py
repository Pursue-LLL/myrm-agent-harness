"""Assertion reconciliation engine maintaining decision lifecycle and resolving overrides.

[INPUT]
- ContextAssertion, AssertionStatus: Domain contracts for decision assertions.

[OUTPUT]
- AssertionReconcileEngine: Tracks assertion states, supercedes obsolete decisions, and eliminates contradictions.

[POS]
Decision reconciliation layer in DAG context subsystem preventing agent cognitive dissonance across long sessions.
"""

from __future__ import annotations

import time
from typing import Sequence

from .dag_types import AssertionStatus, ContextAssertion


class AssertionReconcileEngine:
    """Manages atomic decision assertions and enforces unilateral override semantics."""

    def __init__(self) -> None:
        self._assertions: dict[str, ContextAssertion] = {}
        # topic -> list of assertion_ids in chronological order
        self._topic_index: dict[str, list[str]] = {}

    def register_assertion(
        self,
        assertion_id: str,
        topic: str,
        statement: str,
        origin_turn_id: str = "",
        auto_supersede_previous: bool = True,
    ) -> ContextAssertion:
        """Register a decision assertion, automatically superseding previous active assertions on the same topic."""
        clean_topic = topic.strip().lower()
        now = time.time()

        if auto_supersede_previous and clean_topic in self._topic_index:
            for prev_id in self._topic_index[clean_topic]:
                prev = self._assertions.get(prev_id)
                if prev and prev.status == AssertionStatus.ACTIVE:
                    self._assertions[prev_id] = ContextAssertion(
                        assertion_id=prev.assertion_id,
                        topic=prev.topic,
                        statement=prev.statement,
                        status=AssertionStatus.SUPERSEDED,
                        origin_turn_id=prev.origin_turn_id,
                        superseded_by=assertion_id,
                        created_at=prev.created_at,
                        metadata=prev.metadata,
                    )

        new_assertion = ContextAssertion(
            assertion_id=assertion_id,
            topic=clean_topic,
            statement=statement.strip(),
            status=AssertionStatus.ACTIVE,
            origin_turn_id=origin_turn_id,
            superseded_by="",
            created_at=now,
        )

        self._assertions[assertion_id] = new_assertion
        self._topic_index.setdefault(clean_topic, []).append(assertion_id)
        return new_assertion

    def revoke_assertion(self, assertion_id: str) -> bool:
        """Explicitly revoke an active assertion without introducing a direct replacement."""
        existing = self._assertions.get(assertion_id)
        if not existing or existing.status != AssertionStatus.ACTIVE:
            return False

        self._assertions[assertion_id] = ContextAssertion(
            assertion_id=existing.assertion_id,
            topic=existing.topic,
            statement=existing.statement,
            status=AssertionStatus.REVOKED,
            origin_turn_id=existing.origin_turn_id,
            superseded_by="",
            created_at=existing.created_at,
            metadata=existing.metadata,
        )
        return True

    def get_assertion(self, assertion_id: str) -> ContextAssertion | None:
        """Retrieve a specific assertion by ID."""
        return self._assertions.get(assertion_id)

    def get_active_assertions(self) -> Sequence[ContextAssertion]:
        """Return all currently active assertions in chronological sequence."""
        return tuple(
            a for a in self._assertions.values()
            if a.status == AssertionStatus.ACTIVE
        )

    def get_superseded_assertions(self) -> Sequence[ContextAssertion]:
        """Return all superseded assertions preserved for historical auditing."""
        return tuple(
            a for a in self._assertions.values()
            if a.status == AssertionStatus.SUPERSEDED
        )

    def render_active_assertions_markdown(self) -> str:
        """Render active assertions into a clean prompt block, omitting superseded conflicts."""
        active = self.get_active_assertions()
        if not active:
            return ""

        lines: list[str] = ["### ⚖️ [Reconciled Active Architectural Decisions]"]
        for a in active:
            origin_suffix = f" (Turn: {a.origin_turn_id})" if a.origin_turn_id else ""
            lines.append(f"- **[{a.topic.upper()}]**: {a.statement}{origin_suffix}")
        return "\n".join(lines)
