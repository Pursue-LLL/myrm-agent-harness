"""Structured wiki claims and evidence frontmatter contract.

[INPUT]
utils.markdown_frontmatter (POS: frontmatter block detection)

[OUTPUT]
WikiClaim, WikiEvidence, parse_claims_from_content, validate_compile_claims, ensure_compile_claims,
merge_claims_into_content, resolve_evidence_snapshot_status, resolve_evidence_snapshot_and_excerpt, read_evidence_excerpt, clear_raw_bytes_lru_cache, format_resource_uri, build_evidence_resource_uri,
last_compile_raw_hashes metadata helpers, raw_supersede lineage

[POS]
Parse, validate, and merge OC-compatible `claims` frontmatter for compile output and belief-layer citations.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

CLAIM_STATUSES = frozenset({"supported", "contested", "unsupported", "unknown"})
EvidenceSnapshotStatus = Literal["verified", "stale", "missing"]
MAX_EVIDENCE_EXCERPT_CHARS = 2000
RAW_BYTES_LRU_MAX_BYTES = 32 * 1024 * 1024

LAST_COMPILE_RAW_HASHES_KEY = "last_compile_raw_hashes"
RAW_SUPERSEDE_KEY = "raw_supersede"


@dataclass(frozen=True, slots=True)
class _RawBytesLruEntry:
    mtime_ns: int
    raw: bytes


_RAW_BYTES_LRU: OrderedDict[str, _RawBytesLruEntry] = OrderedDict()
_RAW_BYTES_LRU_TOTAL_BYTES = 0


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
    return all(not (not claim.id.strip() or not claim.text.strip()) for claim in claims)


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


def _parse_evidence_line_range(lines: str) -> tuple[int | None, int | None]:
    cleaned = lines.strip()
    if not cleaned:
        return None, None
    if "-" in cleaned:
        start_part, _, end_part = cleaned.partition("-")
        start_text = start_part.strip()
        end_text = end_part.strip()
        start = int(start_text) if start_text.isdigit() else None
        end = int(end_text) if end_text.isdigit() else None
        return start, end
    if cleaned.isdigit():
        line_no = int(cleaned)
        return line_no, line_no
    return None, None


def _normalize_source_ref(source_ref: str) -> str:
    return source_ref.strip().replace("\\", "/")


def clear_raw_bytes_lru_cache() -> None:
    """Clear the process-wide raw bytes LRU cache (for tests)."""
    _RAW_BYTES_LRU.clear()
    global _RAW_BYTES_LRU_TOTAL_BYTES
    _RAW_BYTES_LRU_TOTAL_BYTES = 0


def _store_raw_bytes_lru(cache_key: str, mtime_ns: int, raw: bytes) -> None:
    global _RAW_BYTES_LRU_TOTAL_BYTES
    existing = _RAW_BYTES_LRU.pop(cache_key, None)
    if existing is not None:
        _RAW_BYTES_LRU_TOTAL_BYTES -= len(existing.raw)
    _RAW_BYTES_LRU[cache_key] = _RawBytesLruEntry(mtime_ns=mtime_ns, raw=raw)
    _RAW_BYTES_LRU_TOTAL_BYTES += len(raw)
    while _RAW_BYTES_LRU and _RAW_BYTES_LRU_TOTAL_BYTES > RAW_BYTES_LRU_MAX_BYTES:
        _, evicted = _RAW_BYTES_LRU.popitem(last=False)
        _RAW_BYTES_LRU_TOTAL_BYTES -= len(evicted.raw)


def _load_raw_bytes(
    source_ref: str,
    structure: WikiStructure | None,
    *,
    cache: dict[str, bytes] | None = None,
) -> bytes:
    if structure is None or not source_ref.strip():
        return b""
    normalized = _normalize_source_ref(source_ref)
    if Path(normalized).is_absolute():
        return b""
    path = _resolve_raw_file(structure, source_ref)
    if path is None:
        return b""
    cache_key = str(path.resolve())
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        return b""
    lru_entry = _RAW_BYTES_LRU.get(cache_key)
    if lru_entry is not None and lru_entry.mtime_ns == mtime_ns:
        _RAW_BYTES_LRU.move_to_end(cache_key)
        raw = lru_entry.raw
    else:
        try:
            raw = path.read_bytes()
        except OSError:
            return b""
        _store_raw_bytes_lru(cache_key, mtime_ns, raw)
    if cache is not None:
        cache[cache_key] = raw
    return raw


def _digest_raw_bytes(raw: bytes) -> str:
    if not raw:
        return ""
    return hashlib.sha256(raw).hexdigest()


def _decode_raw_text(raw: bytes) -> str:
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _slice_excerpt_from_text(text: str, lines: str, max_chars: int) -> str:
    start, end = _parse_evidence_line_range(lines)
    if start is None:
        return ""
    file_lines = text.splitlines()
    start_idx = max(start - 1, 0)
    if end is None:
        selected = file_lines[start_idx:]
    else:
        end_idx = min(max(end, start), len(file_lines))
        selected = file_lines[start_idx:end_idx]
    excerpt = "\n".join(selected).strip()
    if not excerpt:
        return ""
    if len(excerpt) > max_chars:
        return excerpt[:max_chars].rstrip() + "…"
    return excerpt


def read_evidence_excerpt(
    source_ref: str,
    lines: str,
    structure: WikiStructure | None,
    *,
    max_chars: int = MAX_EVIDENCE_EXCERPT_CHARS,
) -> str:
    """Read a bounded excerpt from a raw evidence file using 1-based line ranges."""
    raw = _load_raw_bytes(source_ref, structure)
    text = _decode_raw_text(raw)
    if not text:
        return ""
    return _slice_excerpt_from_text(text, lines, max_chars)


def _content_sha256_for_ref(
    source_ref: str,
    structure: WikiStructure | None,
    *,
    cache: dict[str, bytes] | None = None,
) -> str:
    if structure is None or not source_ref.strip():
        return ""
    if Path(source_ref.strip()).is_absolute():
        return ""
    return _digest_raw_bytes(_load_raw_bytes(source_ref, structure, cache=cache))


def resolve_evidence_snapshot_and_excerpt(
    source_ref: str,
    lines: str,
    pinned_sha256: str,
    structure: WikiStructure | None,
    *,
    cache: dict[str, bytes] | None = None,
    max_chars: int = MAX_EVIDENCE_EXCERPT_CHARS,
) -> tuple[EvidenceSnapshotStatus, str]:
    """Resolve compile snapshot status and raw excerpt from a single raw file read."""
    pinned = pinned_sha256.strip()
    raw = _load_raw_bytes(source_ref, structure, cache=cache)
    digest = _digest_raw_bytes(raw)
    text = _decode_raw_text(raw)
    excerpt = _slice_excerpt_from_text(text, lines, max_chars) if text else ""

    if not pinned:
        status: EvidenceSnapshotStatus = "missing"
    elif not digest:
        status = "missing"
    elif digest == pinned:
        status = "verified"
    else:
        status = "stale"
    return status, excerpt


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


def raw_relative_storage_key(structure: WikiStructure, raw_file: Path) -> str:
    """Return portable raw storage key relative to vault (e.g. raw/notes/budget.md)."""
    rel = raw_file.relative_to(structure.raw_dir).as_posix()
    return f"raw/{rel}"


def sha256_raw_file(raw_file: Path) -> str:
    """Return SHA256 hex digest for a raw file."""
    return hashlib.sha256(raw_file.read_bytes()).hexdigest()


def collect_raw_content_hashes(structure: WikiStructure) -> dict[str, str]:
    """Collect SHA256 digests for all raw markdown files keyed by portable path."""
    hashes: dict[str, str] = {}
    for raw_file in structure.list_raw_files():
        key = raw_relative_storage_key(structure, raw_file)
        try:
            hashes[key] = sha256_raw_file(raw_file)
        except OSError:
            continue
    return hashes


def read_wiki_metadata_file(metadata_path: Path) -> dict[str, object]:
    """Load wiki `.metadata.json` as a mapping."""
    if not metadata_path.exists():
        return {}
    try:
        loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def write_wiki_metadata_merge(metadata_path: Path, updates: dict[str, object]) -> None:
    """Merge updates into wiki metadata JSON."""
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    current = read_wiki_metadata_file(metadata_path)
    current.update(updates)
    metadata_path.write_text(json.dumps(current, indent=2), encoding="utf-8")


def get_last_compile_raw_hashes(metadata: dict[str, object]) -> dict[str, str]:
    """Return last-compile raw hash snapshot from metadata."""
    raw = metadata.get(LAST_COMPILE_RAW_HASHES_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if isinstance(value, str)}


def format_resource_uri(source_path: str, content_sha256: str) -> str:
    """Format portable resource@version URI from path and compile pin digest."""
    path = source_path.strip().replace("\\", "/")
    if path and not path.startswith("raw/"):
        path = f"raw/{path.lstrip('/')}"
    sha = content_sha256.strip()
    if not path or not sha:
        return ""
    return f"{path}@sha256:{sha}"


def normalize_raw_storage_path(source_ref: str) -> str:
    """Normalize evidence path to raw/ relative storage key."""
    cleaned = source_ref.strip().replace("\\", "/")
    if not cleaned:
        return ""
    if cleaned.startswith("raw/"):
        return cleaned
    return f"raw/{cleaned.lstrip('/')}"


def record_raw_supersede_entry(
    structure: WikiStructure,
    *,
    rel_path: str,
    previous_sha256: str,
    new_sha256: str,
    reason: str,
) -> None:
    """Record raw supersede lineage in wiki metadata for citation hints."""
    metadata_path = structure.get_wiki_metadata_path()
    current = read_wiki_metadata_file(metadata_path)
    supersede_raw = current.get(RAW_SUPERSEDE_KEY)
    if not isinstance(supersede_raw, dict):
        supersede_raw = {}
    normalized = normalize_raw_storage_path(rel_path)
    supersede_raw[normalized] = {
        "previous_sha256": previous_sha256,
        "current_sha256": new_sha256,
        "reason": reason,
        "superseded_at": _utc_now_iso(),
    }
    write_wiki_metadata_merge(metadata_path, {RAW_SUPERSEDE_KEY: supersede_raw})


def lookup_raw_supersede_uri(structure: WikiStructure | None, source_ref: str) -> str:
    """Return resource URI for the previous digest when raw was superseded."""
    if structure is None:
        return ""
    metadata = read_wiki_metadata_file(structure.get_wiki_metadata_path())
    supersede_raw = metadata.get(RAW_SUPERSEDE_KEY)
    if not isinstance(supersede_raw, dict):
        return ""
    key = normalize_raw_storage_path(source_ref)
    entry = supersede_raw.get(key)
    if not isinstance(entry, dict):
        return ""
    previous_sha256 = str(entry.get("previous_sha256") or "").strip()
    if not previous_sha256:
        return ""
    return format_resource_uri(key, previous_sha256)


def build_evidence_resource_uri(
    source_path: str,
    pinned_sha256: str,
    *,
    structure: WikiStructure | None = None,
) -> str:
    """Build display URI preferring compile pin, falling back to live raw digest."""
    pinned = pinned_sha256.strip()
    if pinned:
        return format_resource_uri(source_path, pinned)
    live = _content_sha256_for_ref(source_path, structure)
    if live:
        return format_resource_uri(source_path, live)
    return ""
