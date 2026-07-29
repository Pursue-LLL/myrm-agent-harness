"""Wiki canonical identity registry and page lease hashing.

[INPUT]
frontmatter_contract.load_frontmatter_metadata (POS: FM parse SSOT)
structure.WikiStructure (POS: vault concept paths)

[OUTPUT]
build_canonical_index, find_canonical_conflict, derive_canonical_id,
compute_page_lease_hash, stamp_content_hash, ensure_canonical_metadata

[POS]
Write-time dedup and optimistic concurrency for wiki apply mutations.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

CANONICAL_ID_KEY = "canonical_id"
CONTENT_HASH_KEY = "content_hash"


@dataclass(frozen=True, slots=True)
class WikiCanonicalIndex:
    """In-memory map of canonical ids and aliases to concept paths."""

    by_canonical_id: dict[str, str]
    by_alias: dict[str, str]


def normalize_registry_key(value: str) -> str:
    """Normalize a canonical id or alias for case-insensitive lookup."""
    return " ".join(value.strip().lower().split())


def derive_canonical_id(concept_name: str) -> str:
    """Derive a stable canonical id from a concept path when FM omits one."""
    safe = concept_name.strip().lower().replace("\\", "/")
    if safe.endswith(".md"):
        safe = safe[: -len(".md")]
    return safe.replace("/", ".")


def _coerce_aliases(metadata: dict[str, object]) -> tuple[str, ...]:
    raw = metadata.get("aliases")
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if str(item).strip())
    if isinstance(raw, str) and raw.strip():
        return (raw.strip(),)
    return ()


def _concept_name_from_path(structure: WikiStructure, path: Path) -> str:
    rel = path.relative_to(structure.concepts_dir)
    return str(rel.with_suffix("")).replace("\\", "/")


def build_canonical_index(structure: WikiStructure) -> WikiCanonicalIndex:
    """Scan the vault and build canonical id / alias lookup tables."""
    by_canonical_id: dict[str, str] = {}
    by_alias: dict[str, str] = {}

    for path in structure.list_concepts():
        concept_name = _concept_name_from_path(structure, path)
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue

        metadata, _ = load_frontmatter_metadata(content)
        raw_canonical = metadata.get(CANONICAL_ID_KEY)
        canonical_id = (
            normalize_registry_key(str(raw_canonical))
            if raw_canonical
            else derive_canonical_id(concept_name)
        )
        by_canonical_id.setdefault(canonical_id, concept_name)

        for alias in _coerce_aliases(metadata):
            by_alias.setdefault(normalize_registry_key(alias), concept_name)
        by_alias.setdefault(normalize_registry_key(concept_name), concept_name)

    return WikiCanonicalIndex(by_canonical_id=by_canonical_id, by_alias=by_alias)


def find_canonical_conflict(
    index: WikiCanonicalIndex,
    *,
    concept_name: str,
    canonical_id: str | None,
    aliases: tuple[str, ...] | None,
) -> str | None:
    """Return an existing concept path when canonical identity collides."""
    resolved = (
        normalize_registry_key(canonical_id)
        if canonical_id and canonical_id.strip()
        else derive_canonical_id(concept_name)
    )
    existing = index.by_canonical_id.get(resolved)
    if existing and existing != concept_name:
        return existing

    if aliases:
        for alias in aliases:
            target = index.by_alias.get(normalize_registry_key(alias))
            if target and target != concept_name:
                return target
    return None


def compute_page_lease_hash(content: str) -> str:
    """Hash page content excluding the stored lease field itself."""
    metadata, body = load_frontmatter_metadata(content)
    scrubbed = {key: value for key, value in metadata.items() if key != CONTENT_HASH_KEY}
    normalized = serialize_frontmatter_block(scrubbed) + body.lstrip("\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def stamp_content_hash(content: str) -> str:
    """Persist the current lease hash into frontmatter."""
    lease_hash = compute_page_lease_hash(content)
    metadata, body = load_frontmatter_metadata(content)
    metadata[CONTENT_HASH_KEY] = lease_hash
    return serialize_frontmatter_block(metadata) + body.lstrip("\n")


def ensure_canonical_metadata(
    metadata: dict[str, object],
    concept_name: str,
    canonical_id: str | None,
) -> dict[str, object]:
    """Ensure every new page carries a canonical id."""
    if canonical_id and canonical_id.strip():
        metadata[CANONICAL_ID_KEY] = canonical_id.strip()
    elif CANONICAL_ID_KEY not in metadata:
        metadata[CANONICAL_ID_KEY] = derive_canonical_id(concept_name)
    return metadata
