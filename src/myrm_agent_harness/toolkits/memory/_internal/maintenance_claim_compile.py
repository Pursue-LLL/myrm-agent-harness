"""Claim graph compilation for evaporated task digests.

[INPUT]
- maintenance_claim_support (POS: claim helper utilities)
- memory.protocols.vector::VectorStoreProtocol (POS: vector store protocol)
- memory.protocols.graph::GraphStoreProtocol (POS: graph store protocol)

[OUTPUT]
- compile_claim_graph(): compile L2 digests into L3 claim/evidence nodes

[POS]
Claim graph compilation. Builds L3 claim/evidence nodes from evaporated L2 task digests.
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory._internal.storage import _user_filter
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    DigestKind,
    EvaporationState,
    MemoryTier,
)

from myrm_agent_harness.toolkits.memory._internal.maintenance_claim_support import (
    _build_claim_model_summary,
    _classify_claim_relation,
    _classify_result_polarity,
    _freshness_bucket,
    _normalize_change_kind,
    _normalize_claim_key,
    _normalize_scope_fragment,
    _parse_task_digest_fields,
    _scope_from_digest_doc,
    _scope_properties,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol


async def compile_claim_graph(
    vector: VectorStoreProtocol,
    graph: GraphStoreProtocol,
    config: MemoryConfig,
    *,
    limit: int = 100,
) -> int:
    """Compile evaporated L2 digests into minimal L3 claim/evidence nodes."""
    filters = _user_filter()
    filters["event_type"] = "task_digest"
    filters["evaporation_state"] = EvaporationState.EVAPORATED.value
    filters["claim_graph_state"] = ClaimGraphState.PENDING.value

    docs, _ = await vector.scroll(
        config.episodic_collection,
        limit=limit,
        filters=filters,
    )
    if not docs:
        return 0

    compiled_count = 0
    now = datetime.now(UTC)

    for doc in docs:
        fields = _parse_task_digest_fields(doc.content)
        digest_scope = _scope_from_digest_doc(doc)
        digest_scope_channel = digest_scope.channel_id or "unknown"
        freshness_days = max((now - doc.created_at).days, 0)
        claim_key = _normalize_claim_key(fields["title"], fields["goal"])
        scope_fragment = _normalize_scope_fragment(digest_scope.primary_namespace)
        result_polarity = _classify_result_polarity(fields["result"])
        try:
            raw_importance = float(doc.metadata.get("importance", 0.85))
        except (TypeError, ValueError):
            raw_importance = 0.85
        confidence = min(max(raw_importance, 0.5), 0.99)

        evidence_node = await graph.get_or_create_node(
            labels=["Evidence"],
            match_keys=["source_memory_id"],
            properties={
                "id": f"evidence:{doc.id}",
                "source_memory_id": doc.id,
                "title": fields["title"][:120],
                "goal": fields["goal"][:240],
                "result": fields["result"][:240],
                "change_kind": _normalize_change_kind(fields["change_kind"]),
                "key_details": fields["key_details"][:500],
                "source_chat_id": str(doc.metadata.get("source_chat_id", "")),
                "channel_id": digest_scope_channel,
                "freshness_days": freshness_days,
                **_scope_properties(digest_scope),
            },
        )
        claim_text = f"{fields['goal']} -> {fields['result']}"
        base_freshness = _freshness_bucket(freshness_days)
        base_evidence_count = 0
        base_contradiction_status = ClaimConflictState.NONE.value
        model_summary = _build_claim_model_summary(
            title=fields["title"],
            claim_text=claim_text,
            last_result=fields["result"],
            freshness=base_freshness,
            contradiction_status=base_contradiction_status,
            evidence_count=base_evidence_count,
        )
        claim_node = await graph.get_or_create_node(
            labels=["Claim"],
            match_keys=["primary_namespace", "claim_key"],
            properties={
                "id": f"claim:{scope_fragment}:{claim_key}",
                "primary_namespace": digest_scope.primary_namespace,
                "claim_key": claim_key,
                "title": fields["title"][:120],
                "goal": fields["goal"][:240],
                "claim_text": claim_text[:500],
                "change_kind": _normalize_change_kind(fields["change_kind"]),
                "key_details": fields["key_details"][:500],
                "model_summary": model_summary,
                "confidence": round(confidence, 4),
                "freshness_days": freshness_days,
                "freshness": base_freshness,
                "contradiction_status": base_contradiction_status,
                "contradiction_count": 0,
                "evidence_count": base_evidence_count,
                "last_result": fields["result"][:240],
                "result_polarity": result_polarity,
                "latest_relationship_type": "SUPPORTED_BY",
                "last_evidence_at": doc.created_at.isoformat(),
                "latest_channel_id": digest_scope_channel,
                "latest_source_memory_id": doc.id,
                **_scope_properties(digest_scope),
            },
        )
        existing_evidence_count = int(claim_node.properties.get("evidence_count", 0))
        existing_polarity = str(claim_node.properties.get("result_polarity", "neutral"))
        contradiction_count = int(claim_node.properties.get("contradiction_count", 0))
        relationship_type, is_conflicted = _classify_claim_relation(
            existing_goal=str(claim_node.properties.get("goal", "")),
            existing_result=str(claim_node.properties.get("last_result", "")),
            existing_key_details=str(claim_node.properties.get("key_details", "")),
            existing_polarity=existing_polarity,
            new_goal=fields["goal"],
            new_result=fields["result"],
            new_key_details=fields["key_details"],
            new_polarity=result_polarity,
            existing_evidence_count=existing_evidence_count,
            explicit_change_kind=fields["change_kind"],
        )
        if is_conflicted:
            contradiction_count += 1
        updated_contradiction_status = (
            ClaimConflictState.CONFLICTED.value
            if is_conflicted
            else str(claim_node.properties.get("contradiction_status", ClaimConflictState.NONE.value))
        )
        updated_freshness = _freshness_bucket(freshness_days)
        updated_evidence_count = existing_evidence_count + 1
        updated_model_summary = _build_claim_model_summary(
            title=fields["title"],
            claim_text=claim_text,
            last_result=fields["result"],
            freshness=updated_freshness,
            contradiction_status=updated_contradiction_status,
            evidence_count=updated_evidence_count,
        )

        await graph.create_relationship(
            claim_node.id,
            evidence_node.id,
            relationship_type,
            properties={
                "confidence": round(confidence, 4),
                "freshness_days": float(freshness_days),
            },
        )

        updated_claim = await graph.update_node_properties(
            claim_node.id,
            {
                "title": fields["title"][:120],
                "goal": fields["goal"][:240],
                "claim_text": claim_text[:500],
                "change_kind": _normalize_change_kind(fields["change_kind"]),
                "key_details": fields["key_details"][:500],
                "model_summary": updated_model_summary,
                "confidence": round(confidence, 4),
                "freshness_days": freshness_days,
                "freshness": updated_freshness,
                "contradiction_status": updated_contradiction_status,
                "contradiction_count": contradiction_count,
                "evidence_count": updated_evidence_count,
                "last_result": fields["result"][:240],
                "result_polarity": result_polarity,
                "latest_relationship_type": relationship_type,
                "last_evidence_at": doc.created_at.isoformat(),
                "latest_channel_id": digest_scope_channel,
                "latest_source_memory_id": doc.id,
                **_scope_properties(digest_scope),
            },
        )

        contradiction_status = ClaimConflictState.NONE.value
        if updated_claim is not None:
            contradiction_status = str(
                updated_claim.properties.get("contradiction_status", ClaimConflictState.NONE.value)
            )
        doc.metadata["memory_tier"] = MemoryTier.L2.value
        doc.metadata["digest_kind"] = DigestKind.TASK.value
        doc.metadata["evaporation_state"] = EvaporationState.EVAPORATED.value
        doc.metadata["claim_graph_state"] = ClaimGraphState.COMPILED.value
        doc.metadata["claim_graph_node_id"] = claim_node.id
        doc.metadata["claim_graph_updated_at"] = now.isoformat()
        doc.metadata["claim_graph_conflict"] = contradiction_status
        compiled_count += 1

    await vector.upsert(config.episodic_collection, docs)
    return compiled_count
