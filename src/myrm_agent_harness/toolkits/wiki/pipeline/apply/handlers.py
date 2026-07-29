"""Wiki apply operation handlers — narrow writes through section contract.

[INPUT]
..core.section_contract (POS: managed block SSOT)
..core.claims_contract (POS: structured claims merge/reconcile)
..core.frontmatter_contract (POS: YAML frontmatter serialize)
..core.structure::WikiStructure (POS: vault paths)

[OUTPUT]
apply_mutation_to_content: pure content transform for each WikiApplyOp

[POS]
Stateless apply handlers. Caller-aware metadata semantics (settings replace, agent merge).
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    CANONICAL_ID_KEY,
    ensure_canonical_metadata,
)
from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    WikiClaim,
    _claim_slug,
    _parse_claim_entry,
    ensure_compile_claims,
    merge_claims_into_content,
    parse_claims_from_content,
)
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    WikiPageType,
    ensure_frontmatter_type,
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)
from myrm_agent_harness.toolkits.wiki.core.section_contract import (
    COMPILED_TRUTH_HEADING,
    TIMELINE_HEADING,
    append_section_entry,
    build_note_body_skeleton,
    extract_compiled_truth_summary,
    replace_section_inner,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.apply.errors import WikiApplyError
from myrm_agent_harness.toolkits.wiki.pipeline.apply.types import WikiApplyCaller, WikiApplyOp, WikiApplyRequest


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _merge_string_list(existing: object, incoming: tuple[str, ...]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    if isinstance(existing, list):
        for item in existing:
            value = str(item).strip()
            if value and value not in seen:
                seen.add(value)
                merged.append(value)
    for item in incoming:
        value = item.strip()
        if value and value not in seen:
            seen.add(value)
            merged.append(value)
    return merged


def _merge_claims_by_id(existing: tuple[WikiClaim, ...], incoming: tuple[dict[str, object], ...]) -> tuple[WikiClaim, ...]:
    by_id: dict[str, WikiClaim] = {claim.id: claim for claim in existing}
    for raw in incoming:
        parsed = _parse_claim_entry(raw)
        if parsed is None:
            continue
        by_id[parsed.id] = parsed
    return tuple(by_id.values())


def _reconcile_summary_claim(content: str, concept_name: str, structure: WikiStructure) -> str:
    summary = extract_compiled_truth_summary(content)
    if not summary:
        return content
    slug = _claim_slug(concept_name)
    summary_id = f"claim.{slug}.summary"
    existing = parse_claims_from_content(content)
    updated: list[WikiClaim] = []
    found = False
    for claim in existing:
        if claim.id == summary_id:
            updated.append(
                WikiClaim(
                    id=claim.id,
                    text=summary,
                    status=claim.status,
                    confidence=claim.confidence,
                    evidence=claim.evidence,
                    updated_at=_utc_now_iso(),
                )
            )
            found = True
        else:
            updated.append(claim)
    if not found and existing:
        return merge_claims_into_content(content, tuple(updated))
    if not existing:
        return ensure_compile_claims(content, concept_name, [concept_name], structure=structure)
    return merge_claims_into_content(content, tuple(updated))


def _apply_metadata(content: str, request: WikiApplyRequest, *, caller: WikiApplyCaller) -> str:
    metadata, body = load_frontmatter_metadata(content)
    if request.tags is not None:
        if caller == "settings":
            metadata["tags"] = list(request.tags)
        else:
            metadata["tags"] = _merge_string_list(metadata.get("tags"), request.tags)
    if request.aliases is not None:
        if caller == "settings":
            metadata["aliases"] = list(request.aliases)
        else:
            metadata["aliases"] = _merge_string_list(metadata.get("aliases"), request.aliases)
    if request.canonical_id is not None and request.canonical_id.strip():
        metadata[CANONICAL_ID_KEY] = request.canonical_id.strip()
    if request.sources is not None:
        metadata["sources"] = _merge_string_list(metadata.get("sources"), request.sources)
    for key, value in request.metadata.items():
        if value is not None:
            metadata[key] = value
    if request.clear_confidence:
        metadata.pop("confidence", None)
    rebuilt = serialize_frontmatter_block(metadata) + body.lstrip("\n")
    if request.claims:
        merged = _merge_claims_by_id(parse_claims_from_content(rebuilt), request.claims)
        rebuilt = merge_claims_into_content(rebuilt, merged)
    return rebuilt


def _resolve_page_type(raw: str) -> WikiPageType:
    normalized = raw.strip().lower()
    for member in WikiPageType:
        if member.value == normalized:
            return member
    return WikiPageType.SESSION


def apply_mutation_to_content(
    *,
    structure: WikiStructure,
    request: WikiApplyRequest,
    existing_content: str | None,
    caller: WikiApplyCaller = "settings",
) -> tuple[str, bool, bool]:
    """Return (new_content, created, appended)."""
    op = request.op
    concept_name = request.concept_name.strip()
    if not concept_name:
        raise WikiApplyError("invalid_request", "concept_name is required")

    if op == WikiApplyOp.REPLACE_FULL_DOCUMENT:
        if not request.content.strip():
            raise WikiApplyError("invalid_request", "content is required for replace_full_document")
        return request.content, existing_content is None, False

    if op == WikiApplyOp.CREATE_NOTE:
        path = structure.get_concept_file_path(concept_name)
        if path.exists():
            raise WikiApplyError("concept_exists", f"Concept already exists: {concept_name}")
        body_source = request.body.strip() or request.compiled_truth.strip() or request.content.strip()
        timeline_entry = request.timeline_entry.strip() or f"Created at {_utc_now_iso()}"
        body = build_note_body_skeleton(compiled_truth=body_source, timeline_entry=timeline_entry)
        page_type = _resolve_page_type(request.page_type)
        sources = list(request.sources) if request.sources else [concept_name]
        content = ensure_frontmatter_type(
            body,
            page_type,
            sources=sources,
            provenance=request.provenance or "create_note",
        )
        metadata, body_only = load_frontmatter_metadata(content)
        for key, value in request.metadata.items():
            if value is not None:
                metadata[key] = value
        metadata = ensure_canonical_metadata(metadata, concept_name, request.canonical_id)
        if request.tags:
            metadata["tags"] = _merge_string_list(metadata.get("tags"), request.tags)
        if request.aliases:
            metadata["aliases"] = _merge_string_list(metadata.get("aliases"), request.aliases)
        content = serialize_frontmatter_block(metadata) + body_only.lstrip("\n")
        content = ensure_compile_claims(content, concept_name, sources, structure=structure)
        return content, True, False

    if existing_content is None:
        raise WikiApplyError("concept_not_found", f"Concept not found: {concept_name}")

    content = existing_content

    if op == WikiApplyOp.UPDATE_METADATA:
        return _apply_metadata(content, request, caller=caller), False, False

    metadata, body = load_frontmatter_metadata(content)

    if op == WikiApplyOp.PATCH_COMPILED_TRUTH:
        if not request.compiled_truth.strip():
            raise WikiApplyError("invalid_request", "compiled_truth is required for patch_compiled_truth")
        body = replace_section_inner(body, COMPILED_TRUTH_HEADING, request.compiled_truth)
        content = serialize_frontmatter_block(metadata) + body.lstrip("\n")
        content = _reconcile_summary_claim(content, concept_name, structure)
        return content, False, False

    if op == WikiApplyOp.APPEND_TIMELINE:
        entry = request.timeline_entry.strip()
        if not entry:
            raise WikiApplyError("invalid_request", "timeline_entry is required for append_timeline")
        try:
            body, appended = append_section_entry(body, TIMELINE_HEADING, entry)
        except ValueError as exc:
            raise WikiApplyError("timeline_rejected", str(exc)) from exc
        content = serialize_frontmatter_block(metadata) + body.lstrip("\n")
        return content, False, appended

    raise WikiApplyError("unsupported_op", f"Unsupported apply operation: {op.value}")
