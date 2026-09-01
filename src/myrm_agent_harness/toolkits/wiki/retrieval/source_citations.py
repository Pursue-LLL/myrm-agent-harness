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
        return f"kb:LLM-Wiki:{snip.article_path}:claim:{snip.claim_id}:evidence:{snip.evidence_path}:{snip.line_range}"
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
    if snip.article_path:
        from ..core.fact_trust_contract import infer_fact_status_from_path, resolve_fact_status
        entry["fact_status"] = infer_fact_status_from_path(snip.article_path).value
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
        sources_by_key[k].get("snippet") or sources_by_key[k].get("claim_id") for k in ordered_keys
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


_EVIDENCE_CARD_INSTRUCTION = (
    "\n\n[Evidence-Card Answer Contract]\n"
    "- Ground every factual statement in the retrieved snippets with a source reference (e.g. `[source: file.md#Lxx-Lyy]`).\n"
    "- If different sources or notes disagree or present conflicting rules/versions, present BOTH perspectives clearly (`disagree -> show both`).\n"
    "- If the vault contains no relevant facts for a part of the question, honestly state that it is not documented in the vault rather than guessing or filling gaps from general knowledge alone."
)


def format_evidence_cards_context(
    base_answer: str,
    snippets: list[SourceSnippet],
    *,
    structure: WikiStructure | None = None,
) -> str:
    """Format retrieval answer with structured line-level evidence anchors and response contract.

    Injects explicit line range anchors and confidence/status indicators before snippets,
    guaranteeing deterministic citation capabilities and honest conflict disclosure.
    """
    card_sections: list[str] = []

    for snip in snippets:
        if not snip.snippet and not snip.claim_text:
            continue

        header_parts: list[str] = []
        doc_path = snip.evidence_path or snip.article_path
        if doc_path:
            norm_path = doc_path.replace("\\", "/")
            if structure is not None:
                try:
                    p = Path(norm_path)
                    if p.is_absolute():
                        norm_path = str(p.relative_to(structure.vault_dir)).replace("\\", "/")
                except (ValueError, Exception):
                    pass
            if snip.line_range:
                header_parts.append(f"source: {norm_path}#{snip.line_range}")
            else:
                header_parts.append(f"source: {norm_path}")

        if snip.claim_status:
            header_parts.append(f"status: {snip.claim_status}")
        elif snip.evidence_snapshot_status:
            header_parts.append(f"status: {snip.evidence_snapshot_status}")

        if snip.claim_confidence > 0.0 and snip.claim_confidence != 0.5:
            header_parts.append(f"confidence: {snip.claim_confidence:.2f}")

        if snip.hit_kind == "asset" and snip.asset_filename:
            header_parts.append(f"asset: {snip.asset_filename}")
        if snip.section:
            header_parts.append(f"section: {snip.section}")

        header = " | ".join(header_parts)
        if snip.hit_kind == "asset" and snip.snippet:
            text_body = f"Caption: {snip.snippet.strip()}"
        elif snip.claim_text and snip.snippet and snip.snippet.strip() != snip.claim_text.strip():
            text_body = f"Claim: {snip.claim_text.strip()}\nEvidence: {snip.snippet.strip()}"
        else:
            text_body = (snip.snippet or snip.claim_text or "").strip()

        if header:
            card_sections.append(f"--- [Evidence Card: {header}] ---\n{text_body}")
        else:
            card_sections.append(text_body)

    parts: list[str] = []
    trimmed_base = (base_answer or "").strip()
    if trimmed_base:
        parts.append(trimmed_base)

    if card_sections:
        parts.append("## Evidence Snippets & Line Anchors\n" + "\n\n".join(card_sections))

    parts.append(_EVIDENCE_CARD_INSTRUCTION)
    return "\n\n".join(parts)

