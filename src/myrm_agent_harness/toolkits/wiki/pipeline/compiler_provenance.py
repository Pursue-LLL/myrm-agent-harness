"""Compile-time provenance preservation helpers for the wiki compiler.

Provenance metadata (``source_chat`` / ``source_message`` / ``compound_provenance``)
is written by chat-compound staging and auto-archive ingress, but the LLM compile
prompt does not guarantee these custom frontmatter fields survive regeneration.
These helpers re-attach them so knowledge-to-chat traceability survives compiles.

[INPUT]
- ..core.frontmatter_contract::load_frontmatter_metadata, serialize_frontmatter_block (POS: yaml-aware frontmatter read/write)
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer — raw path resolution)

[OUTPUT]
- PROVENANCE_METADATA_KEYS: provenance field names preserved across compiles
- provenance_from_raw_sources: collect provenance from concept raw source files
- restore_provenance_metadata: re-attach provenance onto regenerated article content

[POS]
Compile-time provenance preservation. Kept separate from ``compiler.py`` so the
compiler module stays within the file-line governance baseline while provenance
handling remains independently testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
    serialize_frontmatter_block,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

PROVENANCE_METADATA_KEYS: frozenset[str] = frozenset({"source_chat", "source_message", "compound_provenance"})


def provenance_from_raw_sources(structure: WikiStructure, source_files: list[str]) -> dict[str, str]:
    """Collect provenance metadata from the raw source files of a concept.

    First-compile path: a brand-new concept article has no existing frontmatter to
    restore from, but its raw sources (e.g. auto-archived turn files) carry
    ``source_chat``. Inject it only when all non-empty values agree, so a concept
    merged from multiple unrelated chats does not get a misleading single link.
    """
    collected: dict[str, list[str]] = {key: [] for key in PROVENANCE_METADATA_KEYS}
    for source in source_files:
        # ``concept.source_files`` is derived from the vault-relative doc path
        # (``raw/turn_xxx.md``); ``get_raw_file_path`` expects a raw-relative name.
        cleaned = source.strip().replace("\\", "/").removeprefix("raw/")
        if not cleaned:
            continue
        raw_path = structure.get_raw_file_path(cleaned)
        if not raw_path.exists():
            continue
        try:
            meta, _ = load_frontmatter_metadata(raw_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        for key in PROVENANCE_METADATA_KEYS:
            value = meta.get(key)
            if value is not None and str(value).strip():
                collected[key].append(str(value))

    provenance: dict[str, str] = {}
    for key, values in collected.items():
        unique = list(dict.fromkeys(values))
        if len(unique) == 1:
            provenance[key] = unique[0]
    return provenance


def restore_provenance_metadata(existing_content: str, new_content: str) -> str:
    """Re-attach provenance metadata lost when the LLM regenerates frontmatter.

    Existing values are authoritative and win over any model-written ones.
    """
    if not existing_content:
        return new_content

    existing_meta, _ = load_frontmatter_metadata(existing_content)
    provenance = {
        key: value for key, value in existing_meta.items() if key in PROVENANCE_METADATA_KEYS and value is not None
    }
    if not provenance:
        return new_content

    new_meta, new_body = load_frontmatter_metadata(new_content)
    merged = {**new_meta, **provenance}
    return serialize_frontmatter_block(merged) + new_body.lstrip("\n")
