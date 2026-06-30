"""Claim graph helper utilities for memory maintenance.

[INPUT]
- memory.protocols.graph::GraphStoreProtocol (POS: graph store protocol)
- memory.types::{Claim and scope types} (POS: memory data models)

[OUTPUT]
- Claim parsing, scope normalization, relation classification helpers
- search_claim_graph(): graph search for Claim nodes

[POS]
Internal claim-graph support layer. Parsing, scope normalization, relation classification, and Claim node search.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.types import (
    ClaimMemory,
    MemoryScope,
    MemorySearchResult,
    MemoryType,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.graph import GraphNode, GraphStoreProtocol

logger = logging.getLogger(__name__)

_DIGEST_FIELD_PATTERN = re.compile(r"\*\*(Title|Goal|Result|Change Kind|Key Details)\*\*:\s*(.+)")
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
    namespaces = [ns for ns in raw_namespaces if isinstance(ns, str)] if isinstance(raw_namespaces, list) else []
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
    scope_level = scope.primary_namespace.split(":", 1)[0] if scope.primary_namespace else "global"
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
    primary_namespace = str(claim_node.properties.get("primary_namespace", "")).strip() or "global"
    raw_scope_namespaces = str(claim_node.properties.get("scope_namespaces_json", "")).strip()
    namespaces = [ns for ns in raw_scope_namespaces.split("|") if ns] if raw_scope_namespaces else [primary_namespace]
    return MemoryScope(
        primary_namespace=primary_namespace,
        namespaces=namespaces,
        agent_id=str(claim_node.properties.get("agent_id", "")) or None,
        channel_id=str(claim_node.properties.get("channel_id", "")) or None,
        conversation_id=str(claim_node.properties.get("conversation_id", "")) or None,
        task_id=str(claim_node.properties.get("task_id", "")) or None,
    )


def _claim_node_visible_for_namespaces(claim_node: GraphNode, namespaces: list[str] | None) -> bool:
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
    return {token for token in _QUERY_TOKEN_PATTERN.findall(text.lower()) if len(token) >= 2}


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
    if goal_overlap >= 0.45 and _contains_hint(relation_haystack, _SUPERSEDE_HINTS) and result_overlap < 0.85:
        return "SUPERSEDED_BY", True

    if goal_overlap >= 0.45 and _contains_hint(relation_haystack, _CONSTRAINT_HINTS):
        return "CONSTRAINED_BY", False

    if goal_overlap >= 0.6 and result_overlap < 0.2 and existing_result.strip() and new_result.strip():
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
    return {token for token in _QUERY_TOKEN_PATTERN.findall(query.lower()) if len(token) >= 2}


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
    if current_channel_id and latest_channel_id and latest_channel_id == current_channel_id:
        score += 0.06

    # Importance modulation (confidence as importance proxy, same as sibling scoring)
    confidence = min(max(float(claim_node.properties.get("confidence", 0.75)), 0.0), 1.0)
    score *= 0.7 + 0.3 * confidence

    return max(0.0, min(score, 0.95))


async def search_claim_graph(
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
        score = _score_claim_node(query_tokens, claim_node, current_channel_id=current_channel_id)
        if score <= 0.0:
            continue

        freshness = str(claim_node.properties.get("freshness", "stale"))
        contradiction_status = str(claim_node.properties.get("contradiction_status", "none"))
        claim_scope = _scope_from_claim_node(claim_node)
        latest_channel_id = str(claim_node.properties.get("latest_channel_id", "")) or claim_scope.channel_id
        claim_text = str(claim_node.properties.get("claim_text", "")).strip()
        title = str(claim_node.properties.get("title", "Task Claim")).strip() or "Task Claim"
        last_result = str(claim_node.properties.get("last_result", "")).strip()
        evidence_count = int(claim_node.properties.get("evidence_count", 0))
        model_summary = str(claim_node.properties.get("model_summary", "")).strip() or _build_claim_model_summary(
            title=title,
            claim_text=claim_text,
            last_result=last_result,
            freshness=freshness,
            contradiction_status=contradiction_status,
            evidence_count=evidence_count,
        )

        raw_last_evidence_at = str(claim_node.properties.get("last_evidence_at", "")).strip()
        try:
            claim_timestamp = datetime.fromisoformat(raw_last_evidence_at) if raw_last_evidence_at else now
        except ValueError:
            claim_timestamp = now

        claim_memory = ClaimMemory(
            id=claim_node.id,
            content=model_summary,
            created_at=claim_timestamp,
            updated_at=claim_timestamp,
            importance=min(max(float(claim_node.properties.get("confidence", 0.75)), 0.0), 1.0),
            confidence=min(max(float(claim_node.properties.get("confidence", 0.75)), 0.0), 1.0),
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
                "latest_relationship_type": str(claim_node.properties.get("latest_relationship_type", "")),
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

