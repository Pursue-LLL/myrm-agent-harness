"""Forget raw evidence and re-anchor dependent compiled pages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from myrm_agent_harness.core.security.persistence.content_scan import PersistScanVerdict
from myrm_agent_harness.toolkits.wiki.core.canonical_registry import compute_page_lease_hash
from myrm_agent_harness.toolkits.wiki.core.claims_contract import parse_claims_from_content
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import load_frontmatter_metadata
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.events import WikiMapEvent, WikiMapEventType
from myrm_agent_harness.toolkits.wiki.pipeline.cognitive_map.writer import append_log_entry
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.errors import RawGateError
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate.security_hook import (
    apply_raw_security_scan,
    scan_publish_article_content,
)

RawGateCaller = Literal["agent", "settings", "chat"]


@dataclass(frozen=True, slots=True)
class ForgetEvidenceResult:
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


def _find_affected_concepts(structure: WikiStructure, raw_rel: str) -> list[str]:
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


async def forget_evidence(
    structure: WikiStructure,
    relative_path: str,
    *,
    reason: str,
    caller: RawGateCaller,
    compiler: object | None = None,
    indexer: object | None = None,
) -> ForgetEvidenceResult:
    """Delete a raw file and rescan/republish concepts that referenced it."""
    if caller != "settings":
        raise RawGateError("forbidden_for_caller", "Raw forget is settings-only.")

    trimmed_reason = reason.strip()
    if not trimmed_reason:
        raise RawGateError("invalid_request", "forget_reason is required.")

    rel_path = _normalize_relative_path(relative_path)
    raw_path = structure.get_raw_file_path(rel_path)
    if not raw_path.exists():
        raise RawGateError("not_found", f"Raw source not found: {rel_path}")

    previous_hash = compute_page_lease_hash(raw_path.read_text(encoding="utf-8"))
    affected = _find_affected_concepts(structure, rel_path)
    raw_path.unlink()

    append_log_entry(
        structure,
        WikiMapEvent(
            event_type=WikiMapEventType.EVIDENCE_FORGOTTEN,
            summary=f"Forgot raw evidence {rel_path}",
            details={
                "caller": caller,
                "reason": trimmed_reason,
                "path": rel_path,
                "content_hash": previous_hash,
                "affected_concepts": affected,
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

    return ForgetEvidenceResult(
        relative_path=rel_path,
        deleted=True,
        content_hash=previous_hash,
        affected_concepts=tuple(affected),
        republished_concepts=tuple(republished),
    )


async def scan_existing_raw_vault(
    structure: WikiStructure,
    indexer: object | None = None,
) -> dict[str, object]:
    """Scan all existing raw files; redact in place or remove blocked content."""
    scanned = 0
    redacted = 0
    removed = 0
    paths_redacted: list[str] = []
    paths_removed: list[str] = []

    remove_raw_index = getattr(indexer, "remove_raw_text_index", None)

    for raw_path in structure.list_raw_files("*"):
        if not raw_path.is_file():
            continue
        scanned += 1
        rel = raw_path.relative_to(structure.raw_dir).as_posix()
        original = raw_path.read_text(encoding="utf-8")
        try:
            cleaned = apply_raw_security_scan(
                structure,
                relative_path=rel,
                content=original,
                caller="settings",
            )
        except RawGateError:
            removed += 1
            paths_removed.append(rel)
            append_log_entry(
                structure,
                WikiMapEvent(
                    event_type=WikiMapEventType.RAW_SECURITY,
                    summary=f"Removed blocked raw source: {rel}",
                    details={
                        "caller": "settings",
                        "path": rel,
                        "action": "removed",
                        "reason": "credential_unredactable",
                    },
                ),
            )
            raw_path.unlink(missing_ok=True)
            if callable(remove_raw_index):
                remove_raw_index(raw_path.stem)
            continue
        if cleaned != original:
            raw_path.write_text(cleaned, encoding="utf-8")
            redacted += 1
            paths_redacted.append(rel)

    return {
        "files_scanned": scanned,
        "files_redacted": redacted,
        "files_blocked": removed,
        "files_removed": removed,
        "redacted_paths": paths_redacted,
        "removed_paths": paths_removed,
    }
