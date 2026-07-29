"""Structured wiki claims and evidence frontmatter contract.

[INPUT]
agent.meta_tools.file_ops.utils.markdown_frontmatter (POS: frontmatter block detection)

[OUTPUT]
WikiClaim, WikiEvidence, parse_claims_from_content, validate_compile_claims, ensure_compile_claims,
merge_claims_into_content, resolve_evidence_snapshot_status

[POS]
Parse, validate, and merge OC-compatible `claims` frontmatter for compile output and belief-layer citations.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from myrm_agent_harness.agent.meta_tools.file_ops.utils.markdown_frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

CLAIM_STATUSES = frozenset({"supported", "contested", "unsupported", "unknown"})
EvidenceSnapshotStatus = Literal["verified", "stale", "missing"]


@dataclass(frozen=True, slots=True)
class WikiEvidence:
    """Evidence pointer backing a wiki claim."""

    kind: str
    source_id: str
    path: str
    lines: str
    weight: float
    confidence: float
    note: str
    content_sha256: str = ""
    updated_at: str = ""


@dataclass(frozen=True, slots=True)
class WikiClaim:
    """Structured belief entry stored in concept frontmatter."""

    id: str
    text: str
    status: str
    confidence: float
    evidence: tuple[WikiEvidence, ...]
    updated_at: str = ""


def _parse_frontmatter_mapping(content: str) -> dict[str, object]:
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import load_frontmatter_metadata

    metadata, _body = load_frontmatter_metadata(content)
    return metadata


def _coerce_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _parse_evidence_entry(raw: object) -> WikiEvidence | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or raw.get("evidenceKind") or "").strip()
    source_id = str(raw.get("sourceId") or raw.get("source_id") or "").strip()
    path = str(raw.get("path") or "").strip()
    lines = str(raw.get("lines") or "").strip()
    note = str(raw.get("note") or "").strip()
    content_sha256 = str(raw.get("contentSha256") or raw.get("content_sha256") or "").strip()
    updated_at = str(raw.get("updatedAt") or raw.get("updated_at") or "").strip()
    if not kind and not path and not source_id:
        return None
    return WikiEvidence(
        kind=kind,
        source_id=source_id,
        path=path,
        lines=lines,
        weight=_coerce_float(raw.get("weight"), 1.0),
        confidence=_coerce_float(raw.get("confidence"), 0.0),
        note=note,
        content_sha256=content_sha256,
        updated_at=updated_at,
    )


def _parse_claim_entry(raw: object) -> WikiClaim | None:
    if not isinstance(raw, dict):
        return None
    claim_id = str(raw.get("id") or "").strip()
    text = str(raw.get("text") or "").strip()
    if not claim_id or not text:
        return None
    status = str(raw.get("status") or "unknown").strip().lower()
    if status not in CLAIM_STATUSES:
        status = "unknown"
    updated_at = str(raw.get("updatedAt") or raw.get("updated_at") or "").strip()
    evidence_raw = raw.get("evidence")
    evidence: list[WikiEvidence] = []
    if isinstance(evidence_raw, list):
        for item in evidence_raw:
            parsed = _parse_evidence_entry(item)
            if parsed is not None:
                evidence.append(parsed)
    return WikiClaim(
        id=claim_id,
        text=text,
        status=status,
        confidence=_coerce_float(raw.get("confidence"), 0.0),
        evidence=tuple(evidence),
        updated_at=updated_at,
    )


def parse_claims_from_content(content: str) -> tuple[WikiClaim, ...]:
    """Parse structured claims from wiki concept frontmatter."""
    metadata = _parse_frontmatter_mapping(content)
    claims_raw = metadata.get("claims")
    if not isinstance(claims_raw, list):
        return ()
    parsed: list[WikiClaim] = []
    for item in claims_raw:
        claim = _parse_claim_entry(item)
        if claim is not None:
            parsed.append(claim)
    return tuple(parsed)


def validate_compile_claims(claims: tuple[WikiClaim, ...]) -> bool:
    """Return True when parsed claims are sufficient for compile output."""
    if not claims:
        return False
    for claim in claims:
        if not claim.id.strip() or not claim.text.strip():
            return False
    return True


def _claim_slug(concept_name: str) -> str:
    slug = concept_name.strip().replace("\\", "/").replace("/", ".").replace(" ", "-").lower()
    return slug or "concept"


def _claim_to_mapping(claim: WikiClaim) -> dict[str, object]:
    evidence_items: list[dict[str, object]] = []
    for item in claim.evidence:
        entry: dict[str, object] = {
            "kind": item.kind,
            "sourceId": item.source_id,
            "path": item.path,
            "lines": item.lines,
            "weight": item.weight,
            "confidence": item.confidence,
        }
        if item.note:
            entry["note"] = item.note
        if item.content_sha256:
            entry["contentSha256"] = item.content_sha256
        if item.updated_at:
            entry["updatedAt"] = item.updated_at
        evidence_items.append(entry)
    mapping: dict[str, object] = {
        "id": claim.id,
        "text": claim.text,
        "status": claim.status,
        "confidence": claim.confidence,
        "evidence": evidence_items,
    }
    if claim.updated_at:
        mapping["updatedAt"] = claim.updated_at
    return mapping


def merge_claims_into_content(content: str, claims: tuple[WikiClaim, ...]) -> str:
    """Inject or replace structured claims in concept frontmatter."""
    if not claims:
        return content
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
        load_frontmatter_metadata,
        serialize_frontmatter_block,
    )

    metadata, body = load_frontmatter_metadata(content)
    metadata["claims"] = [_claim_to_mapping(claim) for claim in claims]
    return serialize_frontmatter_block(metadata) + body.lstrip("\n")


def _extract_compiled_truth_summary(content: str) -> str:
    _, body = parse_frontmatter(content)
    truth_match = re.search(r"## Compiled Truth\n(.*?)(?=\n## |$)", body, re.DOTALL)
    summary = truth_match.group(1).strip() if truth_match else body.strip()
    first_line = summary.split("\n", maxsplit=1)[0].strip()
    return first_line[:240] if first_line else ""


def _build_fallback_claims(content: str, concept_name: str, source_files: list[str]) -> tuple[WikiClaim, ...]:
    slug = _claim_slug(concept_name)
    summary = _extract_compiled_truth_summary(content) or f"Compiled summary for {concept_name}"
    evidence: list[WikiEvidence] = []
    for index, source_ref in enumerate(source_files[:3]):
        evidence.append(
            WikiEvidence(
                kind="raw-source",
                source_id=f"source.{slug}.{index}",
                path=source_ref,
                lines="",
                weight=1.0,
                confidence=0.5,
                note="",
            )
        )
    if not evidence:
        evidence.append(
            WikiEvidence(
                kind="compiled-truth",
                source_id=f"concept.{slug}",
                path=concept_name,
                lines="",
                weight=1.0,
                confidence=0.4,
                note="",
            )
        )
    return (
        WikiClaim(
            id=f"claim.{slug}.summary",
            text=summary,
            status="unknown",
            confidence=0.5,
            evidence=tuple(evidence),
        ),
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _resolve_raw_file(structure: WikiStructure, source_ref: str) -> Path | None:
    cleaned = source_ref.strip().replace("\\", "/").removeprefix("raw/")
    if not cleaned:
        return None
    candidates = (
        structure.get_raw_file_path(cleaned),
        structure.get_raw_file_path(Path(cleaned).name),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _content_sha256_for_ref(
    source_ref: str,
    structure: WikiStructure | None,
) -> str:
    if structure is None or not source_ref.strip():
        return ""
    path = _resolve_raw_file(structure, source_ref)
    if path is None:
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def resolve_evidence_snapshot_status(
    source_ref: str,
    pinned_sha256: str,
    structure: WikiStructure | None,
) -> EvidenceSnapshotStatus:
    """Compare pinned compile snapshot against the current raw file digest."""
    pinned = pinned_sha256.strip()
    if not pinned:
        return "missing"
    current = _content_sha256_for_ref(source_ref, structure)
    if not current:
        return "missing"
    if current == pinned:
        return "verified"
    return "stale"


def _pin_claims_with_source_snapshots(
    claims: tuple[WikiClaim, ...],
    structure: WikiStructure | None,
    stamped_at: str,
) -> tuple[WikiClaim, ...]:
    if not claims:
        return claims
    pinned: list[WikiClaim] = []
    for claim in claims:
        evidence_items: list[WikiEvidence] = []
        for evidence in claim.evidence:
            content_sha256 = evidence.content_sha256 or _content_sha256_for_ref(evidence.path, structure)
            evidence_items.append(
                replace(
                    evidence,
                    content_sha256=content_sha256,
                    updated_at=evidence.updated_at or (stamped_at if content_sha256 else ""),
                )
            )
        pinned.append(
            replace(
                claim,
                evidence=tuple(evidence_items),
                updated_at=claim.updated_at or stamped_at,
            )
        )
    return tuple(pinned)


def ensure_compile_claims(
    content: str,
    concept_name: str,
    source_files: list[str],
    *,
    structure: WikiStructure | None = None,
) -> str:
    """Ensure compiled concept content includes valid structured claims frontmatter."""
    stamped_at = _utc_now_iso()
    parsed = parse_claims_from_content(content)
    if validate_compile_claims(parsed):
        claims = parsed
    else:
        claims = _build_fallback_claims(content, concept_name, source_files)
    claims = _pin_claims_with_source_snapshots(claims, structure, stamped_at)
    return merge_claims_into_content(content, claims)
