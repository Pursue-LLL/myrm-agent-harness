"""Shared raw evidence removal and concept re-anchoring.

[INPUT]
- core.structure::WikiStructure (POS: vault paths)
- cognitive_map.writer::append_log_entry (POS: audit log)
- claims_contract::parse_claims_from_content (POS: claims parser)

[OUTPUT]
- RawEvidenceRemovalResult, remove_raw_evidence

[POS]
底层的原始证据移除与概念重锚定通用组件。
"""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.core.security.persistence.content_scan import PersistScanVerdict
from myrm_agent_harness.toolkits.wiki.core.canonical_registry import (
    compute_page_lease_hash,
)
from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    parse_claims_from_content,
)
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import (
    WikiMapEvent,
    WikiMapEventType,
)
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import (
    append_log_entry,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.errors import RawGateError
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.security_hook import (
    scan_publish_article_content,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.types import RawGateCaller


@dataclass(frozen=True, slots=True)
class RawEvidenceRemovalResult:
    relative_path: str
    deleted: bool
    content_hash: str
    affected_concepts: tuple[str, ...]
    republished_concepts: tuple[str, ...]


def _normalize_relative_path(relative_path: str) -> str:
    cleaned = relative_path.strip().replace("\\", "/").lstrip("/")
    if not cleaned:
        raise RawGateError("invalid_request", "relative_path is required")
    return cleaned


def _coerce_sources(metadata: dict[str, object]) -> list[str]:
    raw = metadata.get("sources")
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _concept_references_raw(content: str, raw_rel: str) -> bool:
    metadata, _ = load_frontmatter_metadata(content)
    if raw_rel in _coerce_sources(metadata):
        return True
    claims = parse_claims_from_content(content)
    for claim in claims:
        for evidence in claim.evidence:
            if evidence.path.replace("\\", "/").lstrip("/") == raw_rel:
                return True
    return False


def find_affected_concepts(structure: WikiStructure, raw_rel: str) -> list[str]:
    affected: list[str] = []
    for concept_path in structure.list_concepts():
        rel = str(concept_path.relative_to(structure.concepts_dir).with_suffix("")).replace("\\", "/")
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _concept_references_raw(content, raw_rel):
            affected.append(rel)
    return affected


async def remove_raw_evidence(
    structure: WikiStructure,
    relative_path: str,
    *,
    reason: str,
    caller: RawGateCaller,
    delete_file: bool = True,
    compiler: object | None = None,
    indexer: object | None = None,
) -> RawEvidenceRemovalResult:
    """Remove or detach a raw file and re-anchor dependent compiled pages."""
    if caller != "settings":
        raise RawGateError("forbidden_for_caller", "Raw evidence removal is settings-only.")

    trimmed_reason = reason.strip()
    if not trimmed_reason:
        raise RawGateError("invalid_request", "removal_reason is required.")

    rel_path = _normalize_relative_path(relative_path)
    raw_path = structure.get_raw_file_path(rel_path)
    if not raw_path.exists() and delete_file:
        raise RawGateError("not_found", f"Raw source not found: {rel_path}")

    previous_hash = ""
    if raw_path.exists():
        previous_hash = compute_page_lease_hash(raw_path.read_text(encoding="utf-8"))
    affected = find_affected_concepts(structure, rel_path)
    deleted = False
    if delete_file and raw_path.exists():
        raw_path.unlink()
        deleted = True

    append_log_entry(
        structure,
        WikiMapEvent(
            event_type=WikiMapEventType.EVIDENCE_FORGOTTEN,
            summary=f"Removed raw evidence {rel_path}",
            details={
                "caller": caller,
                "reason": trimmed_reason,
                "path": rel_path,
                "content_hash": previous_hash,
                "affected_concepts": affected,
                "delete_file": delete_file,
            },
        ),
    )

    republished: list[str] = []
    if indexer is not None:
        from myrm_agent_harness.toolkits.wiki.pipeline.publication.publish import (
            ArticlePublishOutcome,
            publish_concept_article,
        )

        for concept_name in affected:
            concept_path = structure.get_concept_file_path(concept_name)
            if not concept_path.exists():
                continue
            body = concept_path.read_text(encoding="utf-8")
            scan = scan_publish_article_content(body)
            if scan.verdict == PersistScanVerdict.BLOCKED:
                continue
            if scan.cleaned_text != body:
                outcome = await publish_concept_article(structure, indexer, concept_name, scan.cleaned_text)
                if outcome == ArticlePublishOutcome.PUBLISHED:
                    republished.append(concept_name)
            else:
                await indexer.upsert(concept_name, body)  # type: ignore[attr-defined]

    if compiler is not None and affected:
        enqueue = getattr(compiler, "enqueue_file", None)
        if callable(enqueue):
            for concept_name in affected:
                concept_path = structure.get_concept_file_path(concept_name)
                if not concept_path.exists():
                    continue
                metadata, _ = load_frontmatter_metadata(concept_path.read_text(encoding="utf-8"))
                for source in _coerce_sources(metadata):
                    if source == rel_path:
                        continue
                    source_path = structure.get_raw_file_path(source)
                    if source_path.exists():
                        enqueue(source_path)

    return RawEvidenceRemovalResult(
        relative_path=rel_path,
        deleted=deleted,
        content_hash=previous_hash,
        affected_concepts=tuple(affected),
        republished_concepts=tuple(republished),
    )
