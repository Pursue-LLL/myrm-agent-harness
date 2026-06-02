"""Background maintenance operations for memory lifecycle.


[INPUT]
- memory._internal.storage::{storage conversion functions} (POS: internal vector storage operations)
- memory.protocols.vector::{VectorDocument, VectorStoreProtocol} (POS: vector store protocol)
- memory.protocols.graph::GraphStoreProtocol (POS: graph store protocol)
- memory.types::{memory data models, Claim types} (POS: memory data models)

[OUTPUT]
- dedup_semantics: Simple vector dedup (similarity ≥0.95, fallback strategy)
- run_forgetting: Five-dimension forgetting execution (time, frequency, importance, relations, rating)
- bump_access_counts: Async access count update (fire-and-forget)
- enrich_with_graph: Graph-enriched retrieval (sibling memories via shared entities)
- compile_claim_graph: Claim Graph compilation (L2 digest → Claim + Evidence nodes)
- evaporate_task_digests: Task Digest evaporation (mark as evaporated)
- sweep_orphaned_blobs: Garbage collect orphaned external BLOB files

[POS]
Stateless background maintenance operations. Handles dedup, forgetting, access tracking,
graph-enriched retrieval, Claim Graph compilation, Task Digest evaporation, and Blob GC.
Called by MemoryManager but fully decoupled from it.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage import (
    _user_filter,
    doc_to_episodic,
    doc_to_semantic,
    embed_single,
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    ClaimMemory,
    DigestKind,
    EpisodicMemory,
    EvaporationState,
    MemoryScope,
    MemorySearchResult,
    MemoryTier,
    MemoryType,
    SemanticMemory,
)

if TYPE_CHECKING:

    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.cache import (
        EmbeddingCacheProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.graph import (
        GraphNode,
        GraphStoreProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
        ForgettingResult,
    )

logger = logging.getLogger(__name__)

_DIGEST_FIELD_PATTERN = re.compile(
    r"\*\*(Title|Goal|Result|Change Kind|Key Details)\*\*:\s*(.+)"
)
_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
_POSITIVE_RESULT_HINTS = (
    "complete",
    "completed",
    "implemented",
    "fixed",
    "resolved",
    "added",
    "enabled",
    "success",
)
_NEGATIVE_RESULT_HINTS = (
    "fail",
    "failed",
    "blocked",
    "error",
    "broken",
    "reverted",
    "removed",
    "disabled",
)
_QUERY_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_SUPERSEDE_HINTS = (
    "migrate",
    "migrated",
    "switched",
    "switch to",
    "replaced",
    "replace",
    "moved to",
    "move to",
    "transitioned",
    "transition to",
    "standardized on",
    "now use",
    "instead of",
)
_CONSTRAINT_HINTS = (
    "requires",
    "require",
    "only if",
    "only when",
    "depends on",
    "blocked by",
    "limited to",
    "fallback",
    "except",
    "unless",
)


async def dedup_semantics(
    memories: list[SemanticMemory],
    vector: VectorStoreProtocol,
    embedding: EmbeddingProtocol,
    config: MemoryConfig,
    cache: EmbeddingCacheProtocol | None,
) -> list[SemanticMemory]:
    """Remove near-duplicate SemanticMemory entries before storing.

    Parallel embedding + parallel search for efficiency.
    Memories with similarity >= 0.95 to an existing entry are silently dropped.
    """
    threshold = 0.95

    for mem in memories:
        if mem.embedding is None:
            mem.embedding = await embed_single(mem.content, embedding, cache)

    async def _is_dup(mem: SemanticMemory) -> bool:
        assert mem.embedding is not None
        try:
            hits = await vector.search(
                config.semantic_collection,
                mem.embedding,
                limit=1,
                filters=None,
                score_threshold=threshold,
            )
            return bool(hits)
        except Exception as exc:
            logger.warning("Dedup search failed (non-fatal): %s", exc)
            return False

    dup_flags = await asyncio.gather(*[_is_dup(m) for m in memories])
    skipped = sum(dup_flags)
    if skipped:
        total = len(memories)
        rate = skipped / total * 100 if total > 0 else 0
        logger.warning(
            "Dedup: skipped %d/%d near-duplicates (rate=%.1f%%)", skipped, total, rate
        )
    return [m for m, is_dup in zip(memories, dup_flags, strict=False) if not is_dup]


async def run_forgetting(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    graph: GraphStoreProtocol | None = None,
) -> ForgettingResult:
    """Scan and process low-retention memories based on ForgettingConfig.mode.

    Modes:
        DELETE  — permanently remove from vector store and graph
        ARCHIVE — mark as archived (metadata update), preserve graph relations
        MARK    — log candidates only, no mutation

    For semantic memories, relation_count is approximated by counting
    vector neighbors (sim > 0.8) to reward well-connected knowledge.
    """
    from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
        ForgettingConfig,
        ForgettingMode,
        ForgettingResult,
        ForgettingStrategy,
    )

    fg_cfg: ForgettingConfig = config.forgetting
    result = ForgettingResult()

    try:
        strategy = ForgettingStrategy(fg_cfg)
        now_iso = datetime.now(UTC).isoformat()

        for collection, converter, estimate_rels in (
            (config.semantic_collection, doc_to_semantic, True),
            (config.episodic_collection, doc_to_episodic, False),
        ):
            docs, _ = await vector.scroll(
                collection,
                limit=fg_cfg.max_forget_per_run * 2,
                filters=None,
            )
            memories = [converter(d) for d in docs]
            rel_counts: dict[str, int] = {}
            if estimate_rels:
                rel_counts = await _estimate_relation_counts(
                    memories,
                    collection,
                    vector,
                )
            candidates = strategy.select_candidates(memories, rel_counts)
            if not candidates:
                continue

            ids = [mem.id for mem, _ in candidates]

            if fg_cfg.mode == ForgettingMode.DELETE:
                result.forgotten_count += await vector.delete(collection, ids)
                result.forgotten_ids.extend(ids)
                if graph is not None:
                    for memory_id in ids:
                        try:
                            await graph.delete_subgraph(memory_id)
                        except Exception as e:
                            logger.warning(
                                "Graph cleanup failed for %s: %s", memory_id, e
                            )
                            result.errors.append((memory_id, str(e)))

            elif fg_cfg.mode == ForgettingMode.ARCHIVE:
                docs_by_id = {d.id: d for d in docs}
                archive_docs: list[VectorDocument] = []
                for mem, score in candidates:
                    doc = docs_by_id.get(mem.id)
                    if doc is None:
                        continue
                    doc.metadata["status"] = "archived"
                    doc.metadata["archived_at"] = now_iso
                    doc.metadata["archive_reason"] = (
                        f"retention={score.total_score:.3f}"
                    )
                    archive_docs.append(doc)
                if archive_docs:
                    await vector.upsert(collection, archive_docs)
                result.archived_count += len(archive_docs)
                result.archived_ids.extend(ids)

            else:
                logger.info(
                    "Forgetting MARK mode: %d candidates in %s (ids: %s)",
                    len(candidates),
                    collection,
                    ids[:5],
                )

        if result.forgotten_count:
            logger.warning(
                "Forgetting DELETE: removed %d memories", result.forgotten_count
            )
        if result.archived_count:
            logger.warning(
                "Forgetting ARCHIVE: archived %d memories", result.archived_count
            )

    except Exception as e:
        logger.warning("Forgetting scan failed (non-fatal): %s", e)

    return result


async def evaporate_task_digests(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    limit: int = 100,
) -> int:
    """Advance pending task digests from L2 pending state to evaporated state.

    This is the minimal lifecycle hook for future L3 compilation. It does not
    build a claim graph yet; it only marks digests as consumed by the
    maintenance pipeline so later compilers can process incrementally.
    """
    filters = _user_filter()
    filters["event_type"] = "task_digest"
    filters["evaporation_state"] = EvaporationState.PENDING.value

    docs, _ = await vector.scroll(
        config.episodic_collection,
        limit=limit,
        filters=filters,
    )
    if not docs:
        return 0

    evaporated_at = datetime.now(UTC).isoformat()
    for doc in docs:
        doc.metadata["memory_tier"] = MemoryTier.L2.value
        doc.metadata["digest_kind"] = DigestKind.TASK.value
        doc.metadata["evaporation_state"] = EvaporationState.EVAPORATED.value
        doc.metadata["evaporated_at"] = evaporated_at
        doc.metadata["claim_graph_state"] = ClaimGraphState.PENDING.value
        doc.metadata["claim_graph_conflict"] = ClaimConflictState.NONE.value

    await vector.upsert(config.episodic_collection, docs)
    return len(docs)




def _parse_task_digest_fields(content: str) -> dict[str, str]:
    parsed = {
        "title": "",
        "goal": "",
        "result": "",
        "change_kind": "",
        "key_details": "",
    }
    for line in content.splitlines():
        match = _DIGEST_FIELD_PATTERN.match(line.strip())
        if not match:
            continue
        field_name, value = match.groups()
        key = field_name.lower().replace(" ", "_")
        parsed[key] = value.strip()

    if not parsed["title"]:
        parsed["title"] = "Task Digest"
    if not parsed["goal"]:
        parsed["goal"] = content.strip()[:160]
    if not parsed["result"]:
        parsed["result"] = "Recorded"
    return parsed


def _normalize_claim_key(title: str, goal: str) -> str:
    base = title.strip().lower() or goal.strip().lower() or "task-digest"
    normalized = _NON_ALNUM_PATTERN.sub("-", base).strip("-")
    return normalized[:96] or "task-digest"


def _normalize_scope_fragment(value: str) -> str:
    normalized = _NON_ALNUM_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized[:64] or "global"


def _scope_from_digest_doc(doc: VectorDocument) -> MemoryScope:
    raw_namespaces = doc.metadata.get("namespaces")
    namespaces = (
        [ns for ns in raw_namespaces if isinstance(ns, str)]
        if isinstance(raw_namespaces, list)
        else []
    )
    primary_namespace = str(doc.metadata.get("primary_namespace", "")).strip()
    if not primary_namespace:
        primary_namespace = namespaces[-1] if namespaces else "global"
    if not namespaces:
        namespaces = [primary_namespace]
    return MemoryScope(
        primary_namespace=primary_namespace,
        namespaces=namespaces,
        agent_id=str(doc.metadata.get("agent_id", "")) or None,
        channel_id=str(doc.metadata.get("channel_id", "")) or None,
        conversation_id=str(doc.metadata.get("conversation_id", "")) or None,
        task_id=str(doc.metadata.get("task_id", "")) or None,
    )


def _scope_properties(scope: MemoryScope) -> dict[str, str]:
    scope_level = (
        scope.primary_namespace.split(":", 1)[0]
        if scope.primary_namespace
        else "global"
    )
    return {
        "primary_namespace": scope.primary_namespace,
        "scope_namespaces_json": "|".join(scope.namespaces),
        "scope_level": scope_level,
        "agent_id": scope.agent_id or "",
        "channel_id": scope.channel_id or "",
        "conversation_id": scope.conversation_id or "",
        "task_id": scope.task_id or "",
    }


def _scope_from_claim_node(claim_node: GraphNode) -> MemoryScope:
    primary_namespace = (
        str(claim_node.properties.get("primary_namespace", "")).strip() or "global"
    )
    raw_scope_namespaces = str(
        claim_node.properties.get("scope_namespaces_json", "")
    ).strip()
    namespaces = (
        [ns for ns in raw_scope_namespaces.split("|") if ns]
        if raw_scope_namespaces
        else [primary_namespace]
    )
    return MemoryScope(
        primary_namespace=primary_namespace,
        namespaces=namespaces,
        agent_id=str(claim_node.properties.get("agent_id", "")) or None,
        channel_id=str(claim_node.properties.get("channel_id", "")) or None,
        conversation_id=str(claim_node.properties.get("conversation_id", "")) or None,
        task_id=str(claim_node.properties.get("task_id", "")) or None,
    )


def _claim_node_visible_for_namespaces(
    claim_node: GraphNode, namespaces: list[str] | None
) -> bool:
    if not namespaces:
        return True
    primary_namespace = str(claim_node.properties.get("primary_namespace", "")).strip()
    return primary_namespace in namespaces


def _classify_result_polarity(result: str) -> str:
    normalized = result.strip().lower()
    if any(hint in normalized for hint in _POSITIVE_RESULT_HINTS):
        return "positive"
    if any(hint in normalized for hint in _NEGATIVE_RESULT_HINTS):
        return "negative"
    return "neutral"


def _text_tokens(text: str) -> set[str]:
    return {
        token for token in _QUERY_TOKEN_PATTERN.findall(text.lower()) if len(token) >= 2
    }


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _text_tokens(left)
    right_tokens = _text_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    intersection = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return intersection / union if union else 0.0


def _contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.strip().lower()
    return any(hint in lowered for hint in hints)


def _normalize_change_kind(change_kind: str) -> str:
    normalized = change_kind.strip().lower()
    aliases = {
        "support": "support",
        "supported": "support",
        "confirm": "support",
        "confirmed": "support",
        "contradict": "contradict",
        "contradicted": "contradict",
        "conflict": "contradict",
        "supersede": "supersede",
        "superseded": "supersede",
        "replace": "supersede",
        "replaced": "supersede",
        "migrate": "supersede",
        "migrated": "supersede",
        "constrain": "constrain",
        "constrained": "constrain",
        "constraint": "constrain",
        "none": "none",
    }
    return aliases.get(normalized, "none")


def _classify_claim_relation(
    *,
    existing_goal: str,
    existing_result: str,
    existing_key_details: str,
    existing_polarity: str,
    new_goal: str,
    new_result: str,
    new_key_details: str,
    new_polarity: str,
    existing_evidence_count: int,
    explicit_change_kind: str,
) -> tuple[str, bool]:
    if existing_evidence_count <= 0:
        return "SUPPORTED_BY", False

    normalized_change_kind = _normalize_change_kind(explicit_change_kind)
    if normalized_change_kind == "support":
        return "SUPPORTED_BY", False
    if normalized_change_kind == "contradict":
        return "CONTRADICTED_BY", True
    if normalized_change_kind == "supersede":
        return "SUPERSEDED_BY", True
    if normalized_change_kind == "constrain":
        return "CONSTRAINED_BY", False

    if (
        existing_polarity in {"positive", "negative"}
        and new_polarity in {"positive", "negative"}
        and existing_polarity != new_polarity
    ):
        return "CONTRADICTED_BY", True

    goal_overlap = _token_overlap(existing_goal, new_goal)
    result_overlap = _token_overlap(existing_result, new_result)
    relation_haystack = " ".join(
        value
        for value in (
            existing_result,
            existing_key_details,
            new_result,
            new_key_details,
        )
        if value.strip()
    )
    if (
        goal_overlap >= 0.45
        and _contains_hint(relation_haystack, _SUPERSEDE_HINTS)
        and result_overlap < 0.85
    ):
        return "SUPERSEDED_BY", True

    if goal_overlap >= 0.45 and _contains_hint(relation_haystack, _CONSTRAINT_HINTS):
        return "CONSTRAINED_BY", False

    if (
        goal_overlap >= 0.6
        and result_overlap < 0.2
        and existing_result.strip()
        and new_result.strip()
    ):
        return "CONTRADICTED_BY", True

    return "SUPPORTED_BY", False


def _freshness_bucket(freshness_days: int) -> str:
    if freshness_days <= 7:
        return "fresh"
    if freshness_days <= 30:
        return "aging"
    return "stale"


def _build_claim_model_summary(
    *,
    title: str,
    claim_text: str,
    last_result: str,
    freshness: str,
    contradiction_status: str,
    evidence_count: int,
) -> str:
    parts = [f"Claim: {title.strip() or 'Task Claim'}"]
    if claim_text.strip():
        parts.append(claim_text.strip())
    if last_result.strip():
        parts.append(f"Latest result: {last_result.strip()}")
    parts.append(f"Freshness: {freshness}")
    parts.append(f"Contradiction: {contradiction_status}")
    parts.append(f"Evidence count: {evidence_count}")
    return " | ".join(parts)[:500]


def _tokenize_query(query: str) -> set[str]:
    return {
        token
        for token in _QUERY_TOKEN_PATTERN.findall(query.lower())
        if len(token) >= 2
    }


def _score_claim_node(
    query_tokens: set[str],
    claim_node: GraphNode,
    *,
    current_channel_id: str | None,
) -> float:
    title = str(claim_node.properties.get("title", "")).lower()
    claim_text = str(claim_node.properties.get("claim_text", "")).lower()
    haystack_tokens = set(_QUERY_TOKEN_PATTERN.findall(f"{title} {claim_text}"))
    overlap = len(query_tokens & haystack_tokens)
    if overlap == 0:
        return 0.0

    score = min(0.55 + overlap * 0.08, 0.88)
    freshness = str(claim_node.properties.get("freshness", "stale"))
    if freshness == "fresh":
        score += 0.08
    elif freshness == "aging":
        score += 0.04

    if str(claim_node.properties.get("contradiction_status", "none")) == "conflicted":
        score -= 0.08

    latest_channel_id = str(claim_node.properties.get("latest_channel_id", ""))
    if (
        current_channel_id
        and latest_channel_id
        and latest_channel_id == current_channel_id
    ):
        score += 0.06

    # Importance modulation (confidence as importance proxy, same as sibling scoring)
    confidence = min(max(float(claim_node.properties.get("confidence", 0.75)), 0.0), 1.0)
    score *= 0.7 + 0.3 * confidence

    return max(0.0, min(score, 0.95))


async def _search_claim_graph(
    graph: GraphStoreProtocol,
    *,
    query: str,
    current_channel_id: str | None,
    namespaces: list[str] | None,
    limit: int,
) -> list[MemorySearchResult]:
    query_tokens = _tokenize_query(query)
    if not query_tokens:
        return []

    candidate_limit = max(limit * 8, 24)
    claim_nodes = await graph.find_nodes(
        ["Claim"],
        {},
        limit=candidate_limit,
    )
    if not claim_nodes:
        return []

    results: list[MemorySearchResult] = []
    now = datetime.now(UTC)
    for claim_node in claim_nodes:
        if not _claim_node_visible_for_namespaces(claim_node, namespaces):
            continue
        score = _score_claim_node(
            query_tokens, claim_node, current_channel_id=current_channel_id
        )
        if score <= 0.0:
            continue

        freshness = str(claim_node.properties.get("freshness", "stale"))
        contradiction_status = str(
            claim_node.properties.get("contradiction_status", "none")
        )
        claim_scope = _scope_from_claim_node(claim_node)
        latest_channel_id = (
            str(claim_node.properties.get("latest_channel_id", ""))
            or claim_scope.channel_id
        )
        claim_text = str(claim_node.properties.get("claim_text", "")).strip()
        title = (
            str(claim_node.properties.get("title", "Task Claim")).strip()
            or "Task Claim"
        )
        last_result = str(claim_node.properties.get("last_result", "")).strip()
        evidence_count = int(claim_node.properties.get("evidence_count", 0))
        model_summary = str(
            claim_node.properties.get("model_summary", "")
        ).strip() or _build_claim_model_summary(
            title=title,
            claim_text=claim_text,
            last_result=last_result,
            freshness=freshness,
            contradiction_status=contradiction_status,
            evidence_count=evidence_count,
        )

        raw_last_evidence_at = str(
            claim_node.properties.get("last_evidence_at", "")
        ).strip()
        try:
            claim_timestamp = (
                datetime.fromisoformat(raw_last_evidence_at)
                if raw_last_evidence_at
                else now
            )
        except ValueError:
            claim_timestamp = now

        claim_memory = ClaimMemory(
            id=claim_node.id,
            content=model_summary,
            created_at=claim_timestamp,
            updated_at=claim_timestamp,
            importance=min(
                max(float(claim_node.properties.get("confidence", 0.75)), 0.0), 1.0
            ),
            confidence=min(
                max(float(claim_node.properties.get("confidence", 0.75)), 0.0), 1.0
            ),
            claim_key=str(claim_node.properties.get("claim_key", "")),
            title=title,
            claim_text=claim_text,
            model_summary=model_summary,
            last_result=last_result,
            evidence_count=evidence_count,
            freshness=freshness,
            freshness_days=int(claim_node.properties.get("freshness_days", 0)),
            contradiction_status=contradiction_status,
            scope=claim_scope,
            metadata={
                "latest_channel_id": latest_channel_id or "",
                "scope_level": str(claim_node.properties.get("scope_level", "")),
                "latest_relationship_type": str(
                    claim_node.properties.get("latest_relationship_type", "")
                ),
            },
        )
        results.append(
            MemorySearchResult(
                memory=claim_memory,
                score=score,
                memory_type=MemoryType.CLAIM,
            )
        )

    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]


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
            else str(
                claim_node.properties.get(
                    "contradiction_status", ClaimConflictState.NONE.value
                )
            )
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

        contradiction_status = (
            str(
                updated_claim.properties.get(
                    "contradiction_status", ClaimConflictState.NONE.value
                )
            )
            if updated_claim is not None
            else ClaimConflictState.NONE.value
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


_RELATION_CONCURRENCY = 10


async def _estimate_relation_counts(
    memories: list[SemanticMemory] | list[EpisodicMemory],
    collection: str,
    vector: VectorStoreProtocol,
) -> dict[str, int]:
    """Approximate relation_count by counting vector neighbors (sim > 0.8).

    Only called for SemanticMemory. Concurrency is capped to avoid
    overwhelming the vector backend.
    """
    embeddable = [
        (m.id, m.embedding) for m in memories if getattr(m, "embedding", None)
    ]
    if not embeddable:
        return {}

    sem = asyncio.Semaphore(_RELATION_CONCURRENCY)

    async def _count(mem_id: str, emb: list[float]) -> tuple[str, int]:
        async with sem:
            try:
                hits = await vector.search(
                    collection,
                    emb,
                    limit=5,
                    filters=None,
                    score_threshold=0.8,
                )
                return mem_id, max(len(hits) - 1, 0)
            except Exception:
                return mem_id, 0

    results = await asyncio.gather(*[_count(mid, emb) for mid, emb in embeddable])
    return dict(results)


async def bump_access_counts(
    results: list[MemorySearchResult],
    vector: VectorStoreProtocol,
    config: MemoryConfig,
) -> None:
    """Fire-and-forget: increment access_count for retrieved memories."""
    try:
        now = datetime.now(UTC)
        for r in results:
            mem = r.memory
            if isinstance(mem, (SemanticMemory, EpisodicMemory)):
                mem.access_count += 1
                mem.last_accessed_at = now
        sem_docs = [
            semantic_to_doc(r.memory)
            for r in results
            if isinstance(r.memory, SemanticMemory)
        ]
        epi_docs = [
            episodic_to_doc(r.memory)
            for r in results
            if isinstance(r.memory, EpisodicMemory)
        ]
        if sem_docs:
            await vector.upsert(config.semantic_collection, sem_docs)
        if epi_docs:
            await vector.upsert(config.episodic_collection, epi_docs)
    except Exception as e:
        logger.warning("Access count update failed (non-fatal): %s", e)


async def sweep_orphaned_blobs(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
) -> int:
    """Garbage collect orphaned external BLOB files.

    Scans the local blob directory and deletes any .gz files that are
    no longer referenced by active ConversationMemory entries in Qdrant.
    """
    import time
    from pathlib import Path

    if not config.blob_storage_enabled:
        return 0

    blob_dir = Path(config.blob_storage_path).expanduser().resolve()
    if not blob_dir.exists() or not blob_dir.is_dir():
        return 0

    # 1. Get all blob files on disk
    disk_blobs = set()
    now_ts = time.time()
    for f in blob_dir.glob("*.gz"):
        if f.is_file():
            # Grace period: skip files modified in the last hour to prevent race conditions
            # with concurrent writes that haven't been committed to Qdrant yet.
            if now_ts - f.stat().st_mtime < 3600:
                continue
            disk_blobs.add(f.stem)  # hash without .gz

    if not disk_blobs:
        return 0

    # 2. Scroll through Qdrant to find active blob pointers
    active_blobs = set()
    next_offset = 0
    while next_offset is not None:
        try:
            docs, next_offset = await vector.scroll(
                config.conversation_collection,
                limit=1000,
                offset=next_offset,
                filters=None,
            )
            if not docs:
                break

            for doc in docs:
                raw_exchange = doc.metadata.get("raw_exchange", "")
                if isinstance(raw_exchange, str) and raw_exchange.startswith("blob://"):
                    blob_hash = raw_exchange[len("blob://") :]
                    active_blobs.add(blob_hash)
        except Exception as e:
            logger.error("Blob GC scroll failed. Aborting GC to prevent data loss: %s", e)
            return 0

    # 3. Delete orphaned blobs
    orphans = disk_blobs - active_blobs
    deleted_count = 0
    for orphan in orphans:
        try:
            (blob_dir / f"{orphan}.gz").unlink(missing_ok=True)
            deleted_count += 1
        except Exception as e:
            logger.warning("Failed to delete orphaned blob %s: %s", orphan, e)

    if deleted_count > 0:
        logger.info("Blob GC: deleted %d orphaned blobs", deleted_count)

    return deleted_count


def _content_hash(content: str) -> str:
    """Calculate normalized MD5 hash for content deduplication.

    Normalizes whitespace and case before hashing so that
    'Hello' and ' hello ' are treated as duplicates.
    """
    normalized = content.strip().lower()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def _freshness_from_age_days(age_days: int) -> str:
    """Convert age in days to freshness bucket."""
    if age_days <= 7:
        return "fresh"
    if age_days <= 30:
        return "aging"
    return "stale"


def _score_sibling_node(
    query_tokens: set[str],
    content: str,
    *,
    depth: int,
    distance_decay: float,
    importance: float,
    created_at: datetime | None,
    current_channel_id: str | None,
    channel_id: str | None,
    now: datetime | None = None,
) -> float:
    """Unified scoring for graph sibling nodes (same formula as Claim Graph).

    Combines: token overlap + distance decay + freshness + importance + channel affinity.
    """
    if not query_tokens:
        return 0.0

    now = now or datetime.now(UTC)
    content_tokens = set(_QUERY_TOKEN_PATTERN.findall(content.lower()))
    overlap = len(query_tokens & content_tokens)
    if overlap == 0:
        return 0.0

    # Token overlap base (mirrors _score_claim_node formula)
    score = min(0.55 + overlap * 0.08, 0.88)

    # Distance decay: depth=1 → 1.0x, depth=2 → decay factor
    score *= distance_decay ** (depth - 1)

    # Freshness boost
    if created_at:
        age_days = max(0, (now - created_at).days)
        freshness = _freshness_from_age_days(age_days)
        if freshness == "fresh":
            score += 0.08
        elif freshness == "aging":
            score += 0.04

    # Importance modulation (episodic memories have importance 0-1)
    score *= 0.7 + 0.3 * max(0.0, min(importance, 1.0))

    # Channel affinity boost
    if current_channel_id and channel_id and current_channel_id == channel_id:
        score += 0.06

    return max(0.0, min(score, 0.95))


async def enrich_with_graph(
    results: list[MemorySearchResult],
    query: str,
    limit: int,
    graph: GraphStoreProtocol,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    *,
    current_channel_id: str | None = None,
    namespaces: list[str] | None = None,
) -> list[MemorySearchResult]:
    """Expand results with graph siblings and Claim Graph recall.

    Optimization features:
    - Unified scoring: token overlap + distance decay + freshness + importance + channel affinity
    - Distance-based scoring: depth=1 gets base score, depth=2 gets base*decay
    - Configurable sibling limit via config.graph_sibling_limit
    - Content-level dedup using MD5 hash
    - Multi-hop traversal via get_related_nodes_with_depth
    """
    existing_ids = {r.id for r in results}
    existing_hashes: set[str] = set()
    claim_results: list[MemorySearchResult] = []
    try:
        claim_results = await _search_claim_graph(
            graph,
            query=query,
            current_channel_id=current_channel_id,
            namespaces=namespaces,
            limit=limit,
        )
    except Exception as e:
        logger.warning("Claim graph search failed (non-fatal): %s", e)

    for claim_result in claim_results:
        if claim_result.id in existing_ids:
            continue
        results.append(claim_result)
        existing_ids.add(claim_result.id)

    episodic_hits = [r for r in results if isinstance(r.memory, EpisodicMemory)]
    if not episodic_hits:
        return results[:limit]

    if vector is None:
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:limit]

    # Multi-hop traversal with depth tracking (parallel)
    related_with_depth: dict[str, int] = {}
    sibling_limit = config.graph_sibling_limit
    max_depth = config.graph_max_depth

    async def _fetch_siblings(memory_id: str) -> list[tuple[str, int]]:
        try:
            return await graph.get_related_nodes_with_depth(
                memory_id, "MENTIONS", max_depth=max_depth
            )
        except Exception:
            try:
                return [(mid, 1) for mid in await graph.get_related_nodes(memory_id, "MENTIONS")]
            except Exception:
                return []

    sibling_lists = await asyncio.gather(
        *[_fetch_siblings(r.memory.id) for r in episodic_hits]
    )
    for siblings in sibling_lists:
        for mid, depth in siblings:
            if mid not in existing_ids and mid not in related_with_depth:
                related_with_depth[mid] = depth

    if not related_with_depth:
        return results

    # Sort by depth (prefer direct siblings) and apply limit
    sorted_ids = sorted(related_with_depth.keys(), key=lambda x: related_with_depth[x])
    limited_ids = sorted_ids[:sibling_limit]

    try:
        docs = await vector.get(config.episodic_collection, limited_ids)
        query_tokens = set(_QUERY_TOKEN_PATTERN.findall(query.lower()))
        now = datetime.now(UTC)
        for doc in docs:
            if doc.metadata.get("status") in (
                "archived",
                "disabled",
            ) or doc.metadata.get("archived"):
                continue

            # Content-level dedup
            content_hash = _content_hash(doc.content)
            if content_hash in existing_hashes:
                continue
            existing_hashes.add(content_hash)

            mem = doc_to_episodic(doc)
            depth = related_with_depth.get(doc.id, 1)

            # Unified scoring (same formula as Claim Graph)
            doc_channel_id = str(doc.metadata.get("channel_id", "")) or None
            latest_at = mem.updated_at or mem.created_at
            score = _score_sibling_node(
                query_tokens=query_tokens,
                content=doc.content,
                depth=depth,
                distance_decay=config.graph_distance_decay,
                importance=mem.importance,
                created_at=latest_at,
                current_channel_id=current_channel_id,
                channel_id=doc_channel_id,
                now=now,
            )

            results.append(
                MemorySearchResult(
                    memory=mem,
                    score=score,
                    memory_type=MemoryType.EPISODIC,
                )
            )
    except Exception as e:
        logger.warning("Graph enrichment failed (non-fatal): %s", e)
    results.sort(key=lambda item: item.score, reverse=True)
    return results[:limit]
