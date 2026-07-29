"""Tests for wiki stale raw-source summary helpers."""

from __future__ import annotations

import json
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.maintenance.stale_summary import (
    collect_stale_raw_path_set,
    concept_uses_stale_sources,
    resolve_raw_file_ingest_status,
)


def _write_metadata(structure: WikiStructure, last_compile_time: str) -> None:
    metadata_path = structure.get_wiki_metadata_path()
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps({"last_compile_time": last_compile_time}), encoding="utf-8")


def test_resolve_raw_file_ingest_status_tri_state(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    _write_metadata(structure, "2020-01-01T00:00:00+00:00")

    raw_file = structure.raw_dir / "notes.md"
    raw_file.write_text("hello", encoding="utf-8")

    stale_paths = collect_stale_raw_path_set(structure)
    assert resolve_raw_file_ingest_status(
        "raw/notes.md",
        stale_paths=stale_paths,
        last_compile_time="2020-01-01T00:00:00+00:00",
    ) == "tracked-modified"

    stale_paths_empty = frozenset()
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
    _write_metadata(structure, "2020-01-01T00:00:00+00:00")
    raw_file = structure.raw_dir / "budget.md"
    raw_file.write_text("Budget details", encoding="utf-8")
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
