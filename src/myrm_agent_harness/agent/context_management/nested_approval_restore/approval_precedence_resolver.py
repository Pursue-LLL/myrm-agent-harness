# [INPUT]: ApprovalDecisionKind, ApprovalDecisionRecord, DecisionPrecedence
# [OUTPUT]: ApprovalPrecedenceResolver
# [POS]: agent/context_management/nested_approval_restore/approval_precedence_resolver.py

"""Precedence resolver enforcing live-decision priority over stale snapshot approvals.

[INPUT]
- ApprovalDecisionKind: Outcome classification enum (approve, reject, pending).
- ApprovalDecisionRecord: Model capturing an approval decision.
- DecisionPrecedence: Hierarchy strategy (LIVE_PRIORITY, SNAPSHOT_ONLY, MERGE_SAVED).

[OUTPUT]
- ApprovalPrecedenceResolver: Resolver arbitrating live vs snapshot approvals and preserving permanent rejections.

[POS]
Decision arbitration engine preventing historical snapshots from overriding live approvals.
"""

from __future__ import annotations

from typing import Sequence

from .nested_approval_types import (
    ApprovalDecisionKind,
    ApprovalDecisionRecord,
    DecisionPrecedence,
)


class ApprovalPrecedenceResolver:
    """Arbitrates approval decisions during nested run restoration."""

    def resolve(
        self,
        snapshot_decisions: Sequence[ApprovalDecisionRecord],
        live_decisions: Sequence[ApprovalDecisionRecord],
        precedence: DecisionPrecedence = DecisionPrecedence.LIVE_PRIORITY,
    ) -> tuple[tuple[ApprovalDecisionRecord, ...], int, int]:
        """Resolve combined approvals, returning (resolved_decisions, live_overrides, permanent_rejections_preserved)."""
        if precedence == DecisionPrecedence.SNAPSHOT_ONLY:
            rejections = sum(
                1 for d in snapshot_decisions if d.decision == ApprovalDecisionKind.REJECT and d.is_permanent
            )
            return tuple(snapshot_decisions), 0, rejections

        # Index live decisions by scope_key (agent_owner::tool_name) and grant_id
        live_by_scope: dict[str, ApprovalDecisionRecord] = {}
        live_by_grant: dict[str, ApprovalDecisionRecord] = {}
        for live in live_decisions:
            live_by_scope[live.scope_key] = live
            live_by_grant[live.grant_id] = live

        resolved_map: dict[str, ApprovalDecisionRecord] = {}
        live_overrides_count = 0
        preserved_rejections = 0

        # Process snapshot decisions
        for snap in snapshot_decisions:
            scope_key = snap.scope_key
            live_match = live_by_scope.get(scope_key) or live_by_grant.get(snap.grant_id)

            if live_match is not None:
                # Conflict exists between snapshot and live
                if precedence == DecisionPrecedence.LIVE_PRIORITY:
                    # LIVE PRIORITY: Live decision always trumps snapshot
                    resolved_map[scope_key] = live_match
                    live_overrides_count += 1
                    if live_match.decision == ApprovalDecisionKind.REJECT and live_match.is_permanent:
                        preserved_rejections += 1
                elif precedence == DecisionPrecedence.MERGE_SAVED:
                    # MERGE SAVED: Permanent rejection in either source trumps everything
                    if live_match.decision == ApprovalDecisionKind.REJECT and live_match.is_permanent:
                        resolved_map[scope_key] = live_match
                        live_overrides_count += 1
                        preserved_rejections += 1
                    elif snap.decision == ApprovalDecisionKind.REJECT and snap.is_permanent:
                        resolved_map[scope_key] = snap
                        preserved_rejections += 1
                    else:
                        # Otherwise take the most recent decision
                        if live_match.timestamp >= snap.timestamp:
                            resolved_map[scope_key] = live_match
                            live_overrides_count += 1
                        else:
                            resolved_map[scope_key] = snap
            else:
                # No live override exists; retain snapshot decision
                resolved_map[scope_key] = snap
                if snap.decision == ApprovalDecisionKind.REJECT and snap.is_permanent:
                    preserved_rejections += 1

        # Also incorporate any live decisions that had no counterpart in snapshot
        for live in live_decisions:
            if live.scope_key not in resolved_map:
                resolved_map[live.scope_key] = live
                if live.decision == ApprovalDecisionKind.REJECT and live.is_permanent:
                    preserved_rejections += 1

        return tuple(resolved_map.values()), live_overrides_count, preserved_rejections
