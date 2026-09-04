"""Stale raw-source summary for wiki compile visibility.

[INPUT]
- ..core.structure::WikiStructure (POS: vault paths and metadata)
- ..core.claims_contract (POS: portable raw hash snapshots)

[OUTPUT]
- collect_stale_raw_files, collect_stale_raw_path_set, concept_uses_stale_sources
- resolve_raw_file_ingest_status, WikiStaleSummary, StaleRawFile

[POS]
Shared stale detection for WikiLinter and product API surfaces. Compares current raw
content digests against the last-compile snapshot in wiki metadata. When compile time
exists but hash snapshot is missing, all current raw files are treated as stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    collect_raw_content_hashes,
    get_last_compile_raw_hashes,
    read_wiki_metadata_file,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


@dataclass(frozen=True, slots=True)
class StaleRawFile:
    """A raw source file whose content digest differs from the last compile snapshot."""

    relative_path: str


@dataclass(frozen=True, slots=True)
class WikiStaleSummary:
    """Aggregate stale-source state for GUI banners and ingest visibility."""

    stale_count: int
    last_compile_time: str | None
    stale_files: tuple[StaleRawFile, ...]


def collect_stale_raw_files(structure: WikiStructure) -> WikiStaleSummary:
    """Return raw files whose content digest differs from the last compile snapshot."""
    metadata_path = structure.get_wiki_metadata_path()
    if not metadata_path.exists():
        return WikiStaleSummary(stale_count=0, last_compile_time=None, stale_files=())

    metadata = read_wiki_metadata_file(metadata_path)
    last_compile = str(metadata.get("last_compile_time", "")).strip()
    if not last_compile:
        return WikiStaleSummary(stale_count=0, last_compile_time=None, stale_files=())

    known_hashes = get_last_compile_raw_hashes(metadata)
    current_hashes = collect_raw_content_hashes(structure)
    from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.eligibility import (
        CorpusEligibilityFilter,
    )
    from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.path_utils import (
        normalize_raw_relative_path,
    )

    blocked = CorpusEligibilityFilter(structure).blocked_paths()
    if blocked:
        known_hashes = {
            normalize_raw_relative_path(key): value
            for key, value in known_hashes.items()
            if normalize_raw_relative_path(key) not in blocked
        }
        current_hashes = {
            normalize_raw_relative_path(key): value
            for key, value in current_hashes.items()
            if normalize_raw_relative_path(key) not in blocked
        }
    if not known_hashes:
        if current_hashes:
            stale = [StaleRawFile(relative_path=key) for key in sorted(current_hashes)]
            return WikiStaleSummary(
                stale_count=len(stale),
                last_compile_time=last_compile,
                stale_files=tuple(stale),
            )
        return WikiStaleSummary(stale_count=0, last_compile_time=last_compile, stale_files=())

    stale: list[StaleRawFile] = []
    for key, current_hash in current_hashes.items():
        if known_hashes.get(key) != current_hash:
            stale.append(StaleRawFile(relative_path=key))

    for key in known_hashes:
        if key not in current_hashes:
            stale.append(StaleRawFile(relative_path=key))

    stale.sort(key=lambda item: item.relative_path)
    return WikiStaleSummary(
        stale_count=len(stale),
        last_compile_time=last_compile,
        stale_files=tuple(stale),
    )


def collect_stale_raw_path_set(structure: WikiStructure) -> frozenset[str]:
    """Return relative paths of stale raw files for tree ingest annotations."""
    summary = collect_stale_raw_files(structure)
    return frozenset(item.relative_path for item in summary.stale_files)


def resolve_raw_file_ingest_status(
    relative_path: str,
    *,
    stale_paths: frozenset[str],
    last_compile_time: str | None,
) -> str | None:
    """Return ingest_status for a raw file path relative to wiki base (e.g. raw/notes.md)."""
    if not last_compile_time:
        return None
    normalized = relative_path.replace("\\", "/")
    if normalized in stale_paths:
        return "tracked-modified"
    bare = normalized.removeprefix("raw/")
    if bare in stale_paths or f"raw/{bare}" in stale_paths:
        return "tracked-modified"
    return "tracked-clean"


def _source_ref_match_keys(source_ref: str) -> frozenset[str]:
    cleaned = source_ref.strip().strip('"').replace("\\", "/")
    if cleaned.startswith("[[") and cleaned.endswith("]]"):
        cleaned = cleaned[2:-2].strip()
    if not cleaned:
        return frozenset()
    keys: set[str] = {cleaned, cleaned.removeprefix("raw/")}
    basename = Path(cleaned).name
    keys.add(basename)
    keys.add(f"raw/{basename}")
    return frozenset(keys)


def concept_uses_stale_sources(content: str, stale_paths: frozenset[str]) -> bool:
    """Return True when concept frontmatter sources or claim evidence reference stale raw files."""
    if not stale_paths:
        return False

    from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
        parse_claims_from_content,
    )
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
        load_frontmatter_metadata,
    )

    metadata, _body = load_frontmatter_metadata(content)
    sources = metadata.get("sources")
    if isinstance(sources, list):
        for item in sources:
            if _source_ref_match_keys(str(item)) & stale_paths:
                return True

    for claim in parse_claims_from_content(content):
        for evidence in claim.evidence:
            if evidence.path and _source_ref_match_keys(evidence.path) & stale_paths:
                return True
    return False
