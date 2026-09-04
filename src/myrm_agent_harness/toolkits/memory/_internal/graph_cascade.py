"""Cascade graph cleanup for derived nodes upon memory deletion."""

from __future__ import annotations

import logging

from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol

logger = logging.getLogger(__name__)


async def cascade_clean_derived_graph_nodes(graph: GraphStoreProtocol | None, memory_id: str) -> None:
    """Remove Claim Graph nodes derived from a deleted/archived memory.

    Evidence nodes carry ``source_memory_id`` pointing back to the original
    vector document.  Claim nodes track ``latest_source_memory_id``.  When
    the original memory is removed, the derived Evidence must be deleted and
    Claim's ``evidence_count`` decremented; a Claim with zero remaining
    Evidence is deleted entirely.
    """
    if graph is None:
        return
    try:
        await graph.delete_subgraph(memory_id)
    except Exception as exc:
        logger.warning("Graph subgraph cleanup failed for %s: %s", memory_id, exc)

    try:
        evidence_nodes = await graph.find_nodes(
            ["Evidence"],
            {"source_memory_id": memory_id},
        )
    except Exception as exc:
        logger.warning("Graph evidence lookup failed for %s: %s", memory_id, exc)
        return

    for evidence in evidence_nodes:
        try:
            await graph.delete_subgraph(evidence.id)
        except Exception as exc:
            logger.warning("Graph evidence delete failed for %s: %s", evidence.id, exc)

    try:
        claim_nodes = await graph.find_nodes(
            ["Claim"],
            {"latest_source_memory_id": memory_id},
        )
    except Exception as exc:
        logger.warning("Graph claim lookup failed for %s: %s", memory_id, exc)
        return

    for claim in claim_nodes:
        evidence_count = int(claim.properties.get("evidence_count", 0))
        if evidence_count <= 1:
            try:
                await graph.delete_subgraph(claim.id)
            except Exception as exc:
                logger.warning("Graph claim delete failed for %s: %s", claim.id, exc)
        else:
            try:
                await graph.update_node_properties(
                    claim.id,
                    {"evidence_count": max(0, evidence_count - 1)},
                )
            except Exception as exc:
                logger.warning("Graph claim update failed for %s: %s", claim.id, exc)
