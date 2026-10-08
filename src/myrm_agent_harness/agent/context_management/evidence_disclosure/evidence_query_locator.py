# [INPUT]: ActionDetailDescriptor, EvidenceRefTarget, QueryScopeKind
# [OUTPUT]: EvidenceQueryLocator, build_action_leaf_ref, build_collection_ref, parse_evidence_ref
# [POS]: agent/context_management/evidence_disclosure/evidence_query_locator.py

"""Deterministic query locator and scope isolator for active and completed evidence.

[INPUT]
- ActionDetailDescriptor: Unified canonical descriptor of an action.
- EvidenceRefTarget: Structured reference target for parsing and matching.
- QueryScopeKind: Deterministic scope constraint (ACTIVE_TURN, COMPLETED_HISTORY, UNIFIED_ALL).

[OUTPUT]
- EvidenceQueryLocator: Deterministic evidence retrieval and scope isolation engine.
- parse_evidence_ref: Parse raw reference string into structured EvidenceRefTarget.
- build_action_leaf_ref: Format leaf reference string for a specific action occurrence.
- build_collection_ref: Format collection reference string for a turn's action set.

[POS]
Query scope determination and action reference locator engine.
"""

from __future__ import annotations

import re
from typing import Sequence

from .evidence_disclosure_types import (
    ActionDetailDescriptor,
    EvidenceRefTarget,
    EvidenceSourceState,
    QueryScopeKind,
)

_COLLECTION_PATTERN = re.compile(
    r"^(session:(?:turn/[0-9]{4}-[0-9]{2}-[0-9]{2}/[1-9][0-9]*|active))#actions$"
)
_LEAF_PATTERN = re.compile(
    r"^(session:(?:turn/[0-9]{4}-[0-9]{2}-[0-9]{2}/[1-9][0-9]*|active))#action/([0-9]+)$"
)
_TURN_PATTERN = re.compile(
    r"^session:(?:turn/[0-9]{4}-[0-9]{2}-[0-9]{2}/[1-9][0-9]*|active)$"
)


def build_collection_ref(turn_ref: str) -> str:
    """Build canonical actions collection reference for a turn."""
    if not _TURN_PATTERN.fullmatch(turn_ref):
        raise ValueError(f"Invalid turn_ref format: {turn_ref}")
    return f"{turn_ref}#actions"


def build_action_leaf_ref(turn_ref: str, occurrence: int) -> str:
    """Build canonical leaf action reference for a specific action index."""
    if not _TURN_PATTERN.fullmatch(turn_ref):
        raise ValueError(f"Invalid turn_ref format: {turn_ref}")
    if occurrence < 0:
        raise ValueError(f"Occurrence must be non-negative, got: {occurrence}")
    return f"{turn_ref}#action/{occurrence}"


def parse_evidence_ref(ref: str) -> EvidenceRefTarget | None:
    """Parse raw ref string into structured EvidenceRefTarget, or None if invalid."""
    col_match = _COLLECTION_PATTERN.fullmatch(ref)
    if col_match is not None:
        return EvidenceRefTarget(
            turn_ref=col_match.group(1),
            occurrence=None,
            is_collection=True,
        )

    leaf_match = _LEAF_PATTERN.fullmatch(ref)
    if leaf_match is not None:
        return EvidenceRefTarget(
            turn_ref=leaf_match.group(1),
            occurrence=int(leaf_match.group(2)),
            is_collection=False,
        )

    turn_match = _TURN_PATTERN.fullmatch(ref)
    if turn_match is not None:
        return EvidenceRefTarget(
            turn_ref=turn_match.group(0),
            occurrence=None,
            is_collection=False,
        )

    return None


class EvidenceQueryLocator:
    """Deterministic locator ensuring query scope isolation between active and history actions."""

    def __init__(self) -> None:
        pass

    def locate(
        self,
        scope: QueryScopeKind,
        *,
        target_ref: str | None = None,
        action_name: str | None = None,
        keyword: str | None = None,
        active_actions: Sequence[ActionDetailDescriptor] = (),
        history_actions: Sequence[ActionDetailDescriptor] = (),
    ) -> tuple[ActionDetailDescriptor, ...]:
        """Locate action evidence within strictly enforced deterministic scopes."""
        candidate_pool: list[ActionDetailDescriptor] = []

        # 1. Enforce deterministic scope boundaries
        if scope in (QueryScopeKind.ACTIVE_TURN, QueryScopeKind.UNIFIED_ALL):
            for action in active_actions:
                if action.source_state == EvidenceSourceState.ACTIVE_TURN:
                    candidate_pool.append(action)

        if scope in (QueryScopeKind.COMPLETED_HISTORY, QueryScopeKind.UNIFIED_ALL):
            for action in history_actions:
                if action.source_state == EvidenceSourceState.COMPLETED_HISTORY:
                    candidate_pool.append(action)

        # 2. Match target ref if specified
        if target_ref is not None:
            parsed = parse_evidence_ref(target_ref)
            if parsed is None:
                # Target ref does not conform to specification
                return ()

            filtered: list[ActionDetailDescriptor] = []
            for item in candidate_pool:
                if parsed.is_collection:
                    if item.turn_ref == parsed.turn_ref:
                        filtered.append(item)
                elif parsed.occurrence is not None:
                    if item.turn_ref == parsed.turn_ref and item.occurrence == parsed.occurrence:
                        filtered.append(item)
                else:
                    if item.turn_ref == parsed.turn_ref:
                        filtered.append(item)
            candidate_pool = filtered

        # 3. Filter by action name if specified
        if action_name is not None:
            candidate_pool = [item for item in candidate_pool if item.action_name == action_name]

        # 4. Filter by keyword if specified (search in request, result, or failure message)
        if keyword is not None and keyword.strip():
            kw_clean = keyword.strip().lower()
            filtered = []
            for item in candidate_pool:
                req_text = str(dict(item.request)).lower()
                res_text = str(item.result).lower() if item.result is not None else ""
                fail_text = item.failure.message.lower() if item.failure is not None else ""
                if kw_clean in req_text or kw_clean in res_text or kw_clean in fail_text or kw_clean in item.action_name.lower():
                    filtered.append(item)
            candidate_pool = filtered

        return tuple(candidate_pool)
