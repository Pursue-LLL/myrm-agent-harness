"""Storage payload helpers for scope, lifecycle, and vector filter generation.

[INPUT]
- memory.protocols.vector::FilterDict (POS: filter dictionary typing)
- memory.types::{ClaimConflictState, ClaimGraphState, DigestKind, EvaporationState, MemoryLifecycle, MemoryScope, MemoryStatus, MemoryTier}

[OUTPUT]
- _safe_float, _safe_int, _status_from_metadata
- _user_filter, _scope_payload, _scope_from_metadata
- _lifecycle_payload, _lifecycle_from_metadata

[POS]
Internal helper functions converting domain lifecycle and scope metadata to/from storage payload structures.
"""

from __future__ import annotations

import logging
from datetime import datetime

from myrm_agent_harness.toolkits.memory.protocols.vector import FilterDict
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    DigestKind,
    EvaporationState,
    MemoryLifecycle,
    MemoryScope,
    MemoryStatus,
    MemoryTier,
)
from myrm_agent_harness.utils.coercion import parse_float, parse_int

logger = logging.getLogger(__name__)


def _safe_float(val: object, default: float = 0.0) -> float:
    return parse_float(val, default)


def _safe_int(val: object, default: int = 0) -> int:
    return parse_int(val, default)


def _status_from_metadata(meta: dict[str, object]) -> MemoryStatus:
    """Restore the unified lifecycle status persisted in the payload."""
    raw = meta.get("status")
    if isinstance(raw, MemoryStatus):
        return raw
    if isinstance(raw, str):
        try:
            return MemoryStatus(raw)
        except ValueError:
            logger.warning("Unknown persisted memory status %r; falling back to ACTIVE", raw)
    if bool(meta.get("archived", False)):
        return MemoryStatus.ARCHIVED
    return MemoryStatus.ACTIVE


def _user_filter(
    *,
    namespaces: list[str] | None = None,
    include_archived: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> FilterDict:
    """Build the standard user-scoped filter for vector queries."""
    f: FilterDict = {"archived": {"not": True}}
    if namespaces:
        f["primary_namespace"] = namespaces
    if include_archived:
        del f["archived"]
    if since is not None or until is not None:
        time_range: dict[str, str | int | float] = {}
        if since is not None:
            time_range["gte"] = since.isoformat()
        if until is not None:
            time_range["lte"] = until.isoformat()
        f["created_at"] = time_range
    return f


def _scope_payload(scope: MemoryScope) -> dict[str, str | list[str]]:
    return {
        "primary_namespace": scope.primary_namespace,
        "namespaces": list(scope.namespaces),
        "agent_id": scope.agent_id or "",
        "channel_id": scope.channel_id or "",
        "conversation_id": scope.conversation_id or "",
        "task_id": scope.task_id or "",
    }


def _scope_from_metadata(meta: dict[str, object]) -> MemoryScope:
    raw_namespaces = meta.get("namespaces", [])
    namespaces = (
        [value for value in raw_namespaces if isinstance(value, str)] if isinstance(raw_namespaces, list) else []
    )
    return MemoryScope(
        primary_namespace=str(meta.get("primary_namespace", "")),
        namespaces=namespaces,
        agent_id=str(meta.get("agent_id", "")) or None,
        channel_id=str(meta.get("channel_id", "")) or None,
        conversation_id=str(meta.get("conversation_id", "")) or None,
        task_id=str(meta.get("task_id", "")) or None,
    )


def _lifecycle_payload(lifecycle: MemoryLifecycle | None) -> dict[str, str]:
    if lifecycle is None:
        return {}
    return {
        "memory_tier": lifecycle.tier.value,
        "digest_kind": (lifecycle.digest_kind.value if lifecycle.digest_kind is not None else ""),
        "evaporation_state": (lifecycle.evaporation_state.value if lifecycle.evaporation_state is not None else ""),
        "evaporated_at": (lifecycle.evaporated_at.isoformat() if lifecycle.evaporated_at is not None else ""),
        "claim_graph_state": (lifecycle.claim_graph_state.value if lifecycle.claim_graph_state is not None else ""),
        "claim_graph_node_id": lifecycle.claim_graph_node_id or "",
        "claim_graph_updated_at": (
            lifecycle.claim_graph_updated_at.isoformat() if lifecycle.claim_graph_updated_at is not None else ""
        ),
        "claim_graph_conflict": (
            lifecycle.claim_graph_conflict.value if lifecycle.claim_graph_conflict is not None else ""
        ),
    }


def _lifecycle_from_metadata(meta: dict[str, object]) -> MemoryLifecycle | None:
    raw_tier = str(meta.get("memory_tier", "")).strip()
    if raw_tier not in {tier.value for tier in MemoryTier}:
        return None

    raw_digest_kind = str(meta.get("digest_kind", "")).strip()
    digest_kind = DigestKind(raw_digest_kind) if raw_digest_kind in {kind.value for kind in DigestKind} else None

    raw_evaporation_state = str(meta.get("evaporation_state", "")).strip()
    evaporation_state = (
        EvaporationState(raw_evaporation_state)
        if raw_evaporation_state in {state.value for state in EvaporationState}
        else None
    )

    raw_claim_graph_state = str(meta.get("claim_graph_state", "")).strip()
    claim_graph_state = (
        ClaimGraphState(raw_claim_graph_state)
        if raw_claim_graph_state in {state.value for state in ClaimGraphState}
        else None
    )

    raw_claim_graph_conflict = str(meta.get("claim_graph_conflict", "")).strip()
    claim_graph_conflict = (
        ClaimConflictState(raw_claim_graph_conflict)
        if raw_claim_graph_conflict in {state.value for state in ClaimConflictState}
        else None
    )

    raw_evaporated_at = str(meta.get("evaporated_at", "")).strip()
    try:
        evaporated_at = datetime.fromisoformat(raw_evaporated_at) if raw_evaporated_at else None
    except ValueError:
        evaporated_at = None

    raw_claim_graph_updated_at = str(meta.get("claim_graph_updated_at", "")).strip()
    try:
        claim_graph_updated_at = (
            datetime.fromisoformat(raw_claim_graph_updated_at) if raw_claim_graph_updated_at else None
        )
    except ValueError:
        claim_graph_updated_at = None

    return MemoryLifecycle(
        tier=MemoryTier(raw_tier),
        digest_kind=digest_kind,
        evaporation_state=evaporation_state,
        evaporated_at=evaporated_at,
        claim_graph_state=claim_graph_state,
        claim_graph_node_id=str(meta.get("claim_graph_node_id", "")) or None,
        claim_graph_updated_at=claim_graph_updated_at,
        claim_graph_conflict=claim_graph_conflict,
    )
