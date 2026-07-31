"""Wiki query citation metadata for chat and memory_search sources.

[INPUT]
- ..core.types::QueryResult, SourceSnippet (POS: Wiki toolkit type definitions)
- ..core.structure::WikiStructure (POS: optional vault paths for live digest fallback)
- ..core.claims_contract::build_evidence_resource_uri (POS: portable resource URI builder)

[OUTPUT]
- build_wiki_query_sources: Deduplicated LLM-Wiki source dicts for SSE metadata (`snippet` raw excerpt, `claim_text`, `claim_confidence`, `resource_uri` / `superseded_from_uri` when `evidence_path` is set).
- attach_wiki_scope_id: Inject logical agent scope into wiki source metadata.

[POS]
Shared citation builder for wiki_query_tool and memory_search wiki corpus. Keeps memory
toolkit free of LangChain tool module dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..core.types import QueryResult, SourceSnippet

if TYPE_CHECKING:
    from ..core.structure import WikiStructure


def wiki_source_dedup_key(snip: SourceSnippet) -> str:
    if snip.hit_kind == "asset" and snip.asset_filename:
        return f"kb:LLM-Wiki:asset:{snip.asset_filename}"
    if snip.claim_id and snip.evidence_path:
        return (
            f"kb:LLM-Wiki:{snip.article_path}:claim:{snip.claim_id}:evidence:{snip.evidence_path}:{snip.line_range}"
        )
    return f"kb:LLM-Wiki:{snip.article_path}:{snip.section}:{snip.level}"


def _evidence_resource_uri_for_snippet(
    snip: SourceSnippet,
    *,
    structure: WikiStructure | None,
) -> str:
    from ..core.claims_contract import build_evidence_resource_uri

    source_path = (snip.evidence_path or "").strip()
    if not source_path:
        return ""
    return build_evidence_resource_uri(
        source_path,
        snip.evidence_content_sha256,
        structure=structure,
    )


def _superseded_from_uri_for_snippet(
    snip: SourceSnippet,
    *,
    structure: WikiStructure | None,
) -> str:
    from ..core.claims_contract import lookup_raw_supersede_uri

    evidence_path = (snip.evidence_path or "").strip()
    if (snip.evidence_snapshot_status or "").strip() != "stale" or not evidence_path:
        return ""
    return lookup_raw_supersede_uri(structure, evidence_path)


def wiki_source_entry(
    snip: SourceSnippet,
    *,
    confidence_score: float,
    structure: WikiStructure | None = None,
) -> dict[str, object]:
    display_name = snip.article_name or Path(snip.article_path).stem or "wiki-source"
    entry: dict[str, object] = {
        "type": "knowledge",
        "kb_name": "LLM-Wiki",
        "filename": display_name,
        "score": confidence_score,
        "path": snip.article_path,
        "source_key": wiki_source_dedup_key(snip),
    }
    if snip.snippet:
        entry["snippet"] = snip.snippet
    if snip.section:
        entry["section"] = snip.section
    if snip.level:
        entry["level"] = snip.level
    if snip.claim_id:
        entry["claim_id"] = snip.claim_id
    if snip.claim_text:
        entry["claim_text"] = snip.claim_text
    if snip.evidence_path:
        entry["evidence_path"] = snip.evidence_path
    if snip.line_range:
        entry["line_range"] = snip.line_range
    if snip.claim_status:
        entry["claim_status"] = snip.claim_status
    if snip.claim_confidence > 0.0 and snip.claim_confidence != 0.5:
        entry["claim_confidence"] = snip.claim_confidence
    if snip.evidence_snapshot_status:
        entry["snapshot_status"] = snip.evidence_snapshot_status
    uri = _evidence_resource_uri_for_snippet(snip, structure=structure)
    if uri:
        entry["resource_uri"] = uri
    superseded_uri = _superseded_from_uri_for_snippet(snip, structure=structure)
    if superseded_uri:
        entry["superseded_from_uri"] = superseded_uri
    if snip.hit_kind == "asset":
        entry["hit_kind"] = "asset"
    if snip.asset_filename:
        entry["asset_filename"] = snip.asset_filename
    return entry


def build_wiki_query_sources(
    result: QueryResult,
    *,
    structure: WikiStructure | None = None,
) -> list[dict[str, object]]:
    """Build deduplicated LLM-Wiki citation metadata from a query result."""
    sources_by_key: dict[str, dict[str, object]] = {}
    ordered_keys: list[str] = []

    for snip in result.source_snippets:
        key = wiki_source_dedup_key(snip)
        if key in sources_by_key:
            entry = sources_by_key[key]
            if snip.snippet:
                entry["snippet"] = snip.snippet
            if snip.evidence_snapshot_status:
                entry["snapshot_status"] = snip.evidence_snapshot_status
            uri = _evidence_resource_uri_for_snippet(snip, structure=structure)
            if uri:
                entry["resource_uri"] = uri
            superseded_uri = _superseded_from_uri_for_snippet(snip, structure=structure)
            if superseded_uri:
                entry["superseded_from_uri"] = superseded_uri
            continue
        sources_by_key[key] = wiki_source_entry(
            snip,
            confidence_score=result.confidence_score,
            structure=structure,
        )
        ordered_keys.append(key)

    snippet_paths = {snip.article_path for snip in result.source_snippets}
    for path_str in result.related_articles:
        if path_str in snippet_paths:
            continue
        path_key = f"kb:LLM-Wiki:{path_str}::L2"
        if path_key in sources_by_key:
            continue
        path = Path(path_str)
        sources_by_key[path_key] = {
            "type": "knowledge",
            "kb_name": "LLM-Wiki",
            "filename": path.stem,
            "score": result.confidence_score,
            "path": path_str,
            "source_key": path_key,
        }
        ordered_keys.append(path_key)

    has_snippet_sources = any(
        sources_by_key[k].get("snippet") or sources_by_key[k].get("claim_id")
        for k in ordered_keys
    )
    return [
        sources_by_key[key]
        for key in ordered_keys
        if sources_by_key[key].get("snippet")
        or sources_by_key[key].get("claim_id")
        or (not has_snippet_sources and key.endswith("::L2"))
    ]


def attach_wiki_scope_id(
    sources: list[dict[str, object]],
    wiki_scope_id: str | None,
) -> list[dict[str, object]]:
    """Attach logical agent scope for wiki asset HTTP URLs."""
    scope = (wiki_scope_id or "").strip()
    if not scope:
        return sources
    scoped: list[dict[str, object]] = []
    for source in sources:
        entry = dict(source)
        entry["agent_id"] = scope
        scoped.append(entry)
    return scoped
