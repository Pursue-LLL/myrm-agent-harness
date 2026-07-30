"""Tests for wiki stale raw-source summary helpers."""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.maintenance.stale_summary import (
    collect_stale_raw_files,
    collect_stale_raw_path_set,
    concept_uses_stale_sources,
    resolve_raw_file_ingest_status,
)


def _write_metadata(structure: WikiStructure, last_compile_time: str, *, raw_hashes: dict[str, str] | None = None) -> None:
    metadata_path = structure.get_wiki_metadata_path()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"last_compile_time": last_compile_time}
    if raw_hashes is not None:
        payload["last_compile_raw_hashes"] = raw_hashes
    metadata_path.write_text(json.dumps(payload), encoding="utf-8")


def test_resolve_raw_file_ingest_status_tri_state(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()

    raw_file = structure.raw_dir / "notes.md"
    raw_file.write_text("hello", encoding="utf-8")

    import hashlib

    current_hash = hashlib.sha256(raw_file.read_bytes()).hexdigest()
    _write_metadata(
        structure,
        "2020-01-01T00:00:00+00:00",
        raw_hashes={"raw/notes.md": "different-hash"},
    )

    stale_paths = collect_stale_raw_path_set(structure)
    assert resolve_raw_file_ingest_status(
        "raw/notes.md",
        stale_paths=stale_paths,
        last_compile_time="2020-01-01T00:00:00+00:00",
    ) == "tracked-modified"

    _write_metadata(
        structure,
        "2099-01-01T00:00:00+00:00",
        raw_hashes={"raw/notes.md": current_hash},
    )
    stale_paths_empty = collect_stale_raw_path_set(structure)
    assert (
        resolve_raw_file_ingest_status(
            "raw/notes.md",
            stale_paths=stale_paths_empty,
            last_compile_time="2099-01-01T00:00:00+00:00",
        )
        == "tracked-clean"
    )
    assert (
        resolve_raw_file_ingest_status(
            "raw/notes.md",
            stale_paths=stale_paths_empty,
            last_compile_time=None,
        )
        is None
    )


def test_concept_uses_stale_sources_matches_claim_evidence(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "budget.md"
    raw_file.write_text("Budget details", encoding="utf-8")
    _write_metadata(
        structure,
        "2020-01-01T00:00:00+00:00",
        raw_hashes={"raw/budget.md": "stale-hash"},
    )
    stale_paths = collect_stale_raw_path_set(structure)

    content = """---
type: concept
claims:
  - id: claim.budget
    text: Budget changed
    status: supported
    evidence:
      - kind: raw-note
        path: raw/budget.md
---
Body
"""
    assert concept_uses_stale_sources(content, stale_paths) is True
    assert concept_uses_stale_sources(content, frozenset()) is False


def test_collect_stale_raw_files_marks_all_raw_when_hash_snapshot_missing(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    (structure.raw_dir / "a.md").write_text("a", encoding="utf-8")
    (structure.raw_dir / "b.md").write_text("b", encoding="utf-8")
    _write_metadata(structure, "2020-01-01T00:00:00+00:00")

    summary = collect_stale_raw_files(structure)
    assert summary.stale_count == 2
    assert {item.relative_path for item in summary.stale_files} == {"raw/a.md", "raw/b.md"}
