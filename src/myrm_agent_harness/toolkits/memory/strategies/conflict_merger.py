"""Deterministic three-state conflict merge and confidence evolution strategy.

Implements pure-functional deterministic admission and merge logic for incoming
memory candidates (Confirm / Supplement / Conflict / Independent).

[INPUT]
- existing: BaseMemory | None
- candidate: ExtractedMemory | BaseMemory | dict[str, object]

[OUTPUT]
- MergeRelation: Tri-state relation classification (CONFIRM / SUPPLEMENT / CONFLICT / INDEPENDENT)
- MergeAction: Operation directive (INSERT / UPDATE / SKIP / SUSPEND)
- MergeResult: Typed execution plan with evolved confidence, merged evidence, and conflict payload
- classify_relation: Pure functional three-state relation classification
- merge_memory_candidate: Main deterministic merge pipeline

[POS]
Memory conflict merge and confidence evolution engine. Pure Python standard library + Pydantic.
Zero network overhead (<0.5ms), zero LLM token cost, 100% deterministic.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    EvidenceReference,
)

logger = logging.getLogger(__name__)

MAX_EVIDENCE_REFERENCES = 50
MAX_CONFIDENCE_CAP = 0.98
CONFIDENCE_STEP_CONFIRM = 0.05
CONFIDENCE_PENALTY_CONFLICT = 0.30
AUTO_UNFREEZE_DAYS = 7
AUTO_UNFREEZE_CONFIRM_COUNT = 3


class MergeRelation(StrEnum):
    """Tri-state relation plus independent classification.

    - CONFIRM: New fact reinforces existing fact with equivalent meaning or values.
    - SUPPLEMENT: New fact extends, adds non-conflicting attributes or superset detail.
    - CONFLICT: Direct contradiction or mutually exclusive settings (requires human governance).
    - INDEPENDENT: Unrelated fact, safe to store independently.
    """

    CONFIRM = "confirm"
    SUPPLEMENT = "supplement"
    CONFLICT = "conflict"
    INDEPENDENT = "independent"


class MergeAction(StrEnum):
    """Action directive for storage pipeline."""

    INSERT = "insert"
    UPDATE = "update"
    SKIP = "skip"
    SUSPEND = "suspend"


class ConflictDetail(BaseModel):
    """Structured conflict payload preserved for governance review."""

    existing_value: Any = Field(..., description="Existing recorded fact or value")
    candidate_value: Any = Field(..., description="Contradicting candidate fact or value")
    conflict_key: str | None = Field(default=None, description="Conflicting property or category key")
    reason: str = Field(..., description="Detailed explanation of contradiction")
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MergeResult(BaseModel):
    """Deterministic merge plan and confidence evolution result."""

    action: MergeAction = Field(..., description="Action to take in memory store")
    relation: MergeRelation = Field(..., description="Tri-state relation classification")
    value: Any = Field(default=None, description="Final or updated value payload")
    confidence: float = Field(..., description="Evolved confidence score (0.0 - 1.0)")
    evidence: list[EvidenceReference] = Field(
        default_factory=list, description="Merged deduplicated evidence provenance chain"
    )
    conflict: ConflictDetail | None = Field(
        default=None, description="Populated when relation is CONFLICT"
    )
    is_user_locked: bool = Field(
        default=False, description="Whether this memory is protected by human override"
    )
    skip_reason: str | None = Field(
        default=None, description="Reason if action is SKIP"
    )
    requires_governance: bool = Field(
        default=False, description="True if human intervention is required"
    )


def merge_evidence_references(
    existing: Sequence[EvidenceReference] | None,
    incoming: Sequence[EvidenceReference] | None,
    *,
    max_items: int = MAX_EVIDENCE_REFERENCES,
) -> list[EvidenceReference]:
    """Merge two evidence reference sequences, preserving newer ones first and deduplicating."""
    merged: list[EvidenceReference] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    # Incoming evidence placed first (recent interactions prioritized for review)
    combined: list[EvidenceReference] = list(incoming or []) + list(existing or [])
    for ev in combined:
        if not isinstance(ev, EvidenceReference):
            continue
        key = (ev.source_id, ev.message_id, ev.quote_snippet)
        if key not in seen:
            seen.add(key)
            merged.append(ev)
            if len(merged) >= max_items:
                break
    return merged


def _normalize_comparable(val: Any) -> Any:
    """Normalize values for deterministic structural comparison."""
    if isinstance(val, (int, float, bool, str)) or val is None:
        return val
    if isinstance(val, (list, tuple, set)):
        return sorted([_normalize_comparable(x) for x in val], key=lambda x: str(x))
    if isinstance(val, dict):
        return {str(k): _normalize_comparable(v) for k, v in sorted(val.items())}
    if hasattr(val, "model_dump"):
        return _normalize_comparable(val.model_dump())
    if hasattr(val, "__dict__"):
        return _normalize_comparable(vars(val))
    return str(val)


def classify_relation(existing_val: Any, candidate_val: Any) -> MergeRelation:
    """Pure structural comparison without LLM cost.

    Classifies relation into CONFIRM, SUPPLEMENT, or CONFLICT.
    """
    norm_existing = _normalize_comparable(existing_val)
    norm_candidate = _normalize_comparable(candidate_val)

    if norm_existing == norm_candidate:
        return MergeRelation.CONFIRM

    # Array / List: If candidate contains all elements of existing plus more -> SUPPLEMENT
    if isinstance(norm_existing, list) and isinstance(norm_candidate, list):
        existing_str_set = {json.dumps(x, sort_keys=True) for x in norm_existing}
        candidate_str_set = {json.dumps(x, sort_keys=True) for x in norm_candidate}
        if existing_str_set.issubset(candidate_str_set):
            return MergeRelation.SUPPLEMENT
        # Overlapping elements but disjoint differences -> CONFLICT
        return MergeRelation.CONFLICT

    # Dict / Map: Check key-by-key
    if isinstance(norm_existing, dict) and isinstance(norm_candidate, dict):
        overlap_keys = set(norm_existing.keys()) & set(norm_candidate.keys())
        has_conflict = False
        has_new_keys = bool(set(norm_candidate.keys()) - set(norm_existing.keys()))

        for k in overlap_keys:
            if norm_existing[k] != norm_candidate[k]:
                has_conflict = True
                break

        if has_conflict:
            return MergeRelation.CONFLICT
        if has_new_keys:
            return MergeRelation.SUPPLEMENT
        return MergeRelation.CONFIRM

    # Scalar / string comparison: Different scalar values mean contradiction
    return MergeRelation.CONFLICT


def check_procedural_relation(existing_mem: Any, candidate_mem: Any) -> MergeRelation:
    """Specialized tri-state relation check for procedural / behavioral rules.

    Compares triggers, tool names, actions, and priority.
    """
    ex_trigger = str(getattr(existing_mem, "trigger", "") or "").strip().lower()
    can_trigger = str(getattr(candidate_mem, "trigger", "") or "").strip().lower()

    # Different triggers -> Independent rules
    if ex_trigger != can_trigger:
        return MergeRelation.INDEPENDENT

    ex_tool = str(getattr(existing_mem, "tool_name", "") or "").strip().lower()
    can_tool = str(getattr(candidate_mem, "tool_name", "") or "").strip().lower()

    ex_action = str(getattr(existing_mem, "action", "") or getattr(existing_mem, "content", "") or "").strip()
    can_action = str(getattr(candidate_mem, "action", "") or getattr(candidate_mem, "content", "") or "").strip()

    # Same trigger, identical tool and action -> Confirm
    if ex_tool == can_tool and ex_action == can_action:
        return MergeRelation.CONFIRM

    # Same trigger, same tool, candidate action is longer/detailed extension -> Supplement
    if ex_tool == can_tool and (ex_action in can_action or not ex_action):
        return MergeRelation.SUPPLEMENT

    # Same trigger, different tool or mutually contradictory action -> Conflict
    return MergeRelation.CONFLICT


def merge_memory_candidate(
    existing: BaseMemory | Any | None,
    candidate: Any,
    *,
    candidate_source: str = "assistant_distillation",
    now: datetime | None = None,
) -> MergeResult:
    """Execute deterministic three-state merge and confidence evolution.

    - Protects user-locked memories (User Override Wins).
    - Smooths confidence mathematically (+0.05 on Confirm, drops to 0.30 on Conflict).
    - Merges and deduplicates evidence references.
    - Evaluates auto-unfreeze conditions for stale conflicts.
    """
    current_time = now or datetime.now(UTC)

    # 1. First-time insertion (Null existing)
    if existing is None:
        raw_evidence = getattr(candidate, "evidence", [])
        evidence_list = [ev for ev in raw_evidence if isinstance(ev, EvidenceReference)]
        initial_conf = float(getattr(candidate, "confidence", 0.8) or 0.8)
        return MergeResult(
            action=MergeAction.INSERT,
            relation=MergeRelation.INDEPENDENT,
            value=getattr(candidate, "content", str(candidate)),
            confidence=initial_conf,
            evidence=evidence_list[:MAX_EVIDENCE_REFERENCES],
            is_user_locked=bool(getattr(candidate, "is_user_locked", False)),
        )

    # 2. Extract metadata & User Override Wins rule
    existing_locked = bool(
        getattr(existing, "is_user_locked", False)
        or getattr(existing, "user_pinned", False)
        or getattr(existing, "source", "") == "user"
    )
    candidate_is_user = candidate_source == "user" or getattr(candidate, "source", "") == "user"

    # CRITICAL: User override wins. Automated pipelines can never silently overwrite human edits!
    if existing_locked and not candidate_is_user:
        return MergeResult(
            action=MergeAction.SKIP,
            relation=MergeRelation.CONFLICT,
            value=getattr(existing, "content", ""),
            confidence=float(getattr(existing, "confidence", 1.0) or 1.0),
            evidence=getattr(existing, "evidence", []) or [],
            is_user_locked=True,
            skip_reason="user_override_wins",
            requires_governance=True,
            conflict=ConflictDetail(
                existing_value=getattr(existing, "content", ""),
                candidate_value=getattr(candidate, "content", ""),
                reason="Candidate attempted to overwrite user-locked memory. Protected by User Override Wins.",
                detected_at=current_time,
            ),
        )

    # 3. Determine Values & Relation
    ex_val = getattr(existing, "value", None) or getattr(existing, "content", "")
    can_val = getattr(candidate, "value", None) or getattr(candidate, "content", "")

    mem_type = getattr(existing, "memory_type", None) or getattr(existing, "type", None)
    if str(mem_type).lower() in ("procedural", "proceduralmemory"):
        relation = check_procedural_relation(existing, candidate)
    else:
        relation = classify_relation(ex_val, can_val)

    # 4. Prepare Evidence
    ex_evidence = getattr(existing, "evidence", []) or []
    can_evidence = getattr(candidate, "evidence", []) or []
    merged_ev = merge_evidence_references(ex_evidence, can_evidence)

    existing_conf = float(getattr(existing, "confidence", 0.8) or 0.8)
    can_conf = float(getattr(candidate, "confidence", 0.8) or 0.8)

    # 5. Handle Tri-State Actions
    if relation == MergeRelation.CONFIRM:
        bumped_conf = min(MAX_CONFIDENCE_CAP, existing_conf + CONFIDENCE_STEP_CONFIRM)
        return MergeResult(
            action=MergeAction.UPDATE,
            relation=MergeRelation.CONFIRM,
            value=getattr(existing, "content", ex_val),
            confidence=bumped_conf,
            evidence=merged_ev,
            is_user_locked=existing_locked,
        )

    if relation == MergeRelation.SUPPLEMENT:
        # Inherit higher confidence and take augmented candidate value
        supp_conf = max(existing_conf, can_conf)
        return MergeResult(
            action=MergeAction.UPDATE,
            relation=MergeRelation.SUPPLEMENT,
            value=getattr(candidate, "content", can_val),
            confidence=supp_conf,
            evidence=merged_ev,
            is_user_locked=existing_locked,
        )

    if relation == MergeRelation.CONFLICT:
        # Check auto-unfreeze condition:
        # If candidate has been repeatedly verified (≥ 3 times) over time (≥ 7 days),
        # natural migration occurs, resolving the stale conflict.
        created_at = getattr(existing, "created_at", None)
        can_meta = getattr(candidate, "metadata", {}) or {}
        confirm_count = int(
            can_meta.get("confirm_count")
            or getattr(candidate, "confirm_count", None)
            or 1
        )
        if (
            created_at
            and isinstance(created_at, datetime)
            and (current_time - (created_at if created_at.tzinfo else created_at.replace(tzinfo=UTC)))
            >= timedelta(days=AUTO_UNFREEZE_DAYS)
            and confirm_count >= AUTO_UNFREEZE_CONFIRM_COUNT
        ):
            logger.info("Conflict auto-unfrozen by steady continuous behavior over %d days", AUTO_UNFREEZE_DAYS)
            return MergeResult(
                action=MergeAction.UPDATE,
                relation=MergeRelation.SUPPLEMENT,
                value=getattr(candidate, "content", can_val),
                confidence=can_conf,
                evidence=merged_ev,
                is_user_locked=False,
                skip_reason="auto_unfrozen_superseded",
            )

        # Real Conflict: Retain both conclusions, penalize confidence to 0.30, suspend for governance
        return MergeResult(
            action=MergeAction.SUSPEND,
            relation=MergeRelation.CONFLICT,
            value=getattr(candidate, "content", can_val),
            confidence=CONFIDENCE_PENALTY_CONFLICT,
            evidence=merged_ev,
            is_user_locked=existing_locked,
            requires_governance=True,
            conflict=ConflictDetail(
                existing_value=getattr(existing, "content", ex_val),
                candidate_value=getattr(candidate, "content", can_val),
                reason="Direct contradiction detected. Both conclusions retained under reduced confidence.",
                detected_at=current_time,
            ),
        )

    # Independent: return insert directive
    return MergeResult(
        action=MergeAction.INSERT,
        relation=MergeRelation.INDEPENDENT,
        value=getattr(candidate, "content", can_val),
        confidence=can_conf,
        evidence=merged_ev,
        is_user_locked=False,
    )
