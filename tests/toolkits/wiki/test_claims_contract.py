"""Tests for wiki claims frontmatter contract."""

from __future__ import annotations

import hashlib
import json

from myrm_agent_harness.toolkits.wiki.core.claims_contract import (
    RAW_SUPERSEDE_KEY,
    build_evidence_resource_uri,
    collect_raw_content_hashes,
    ensure_compile_claims,
    format_resource_uri,
    lookup_raw_supersede_uri,
    parse_claims_from_content,
    record_raw_supersede_entry,
    validate_compile_claims,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


def test_parse_claims_from_content_reads_structured_claims() -> None:
    content = """---
type: concept
claims:
  - id: claim.budget.q3
    text: Q3 budget is 50M
    status: supported
    confidence: 0.95
    evidence:
      - kind: raw-note
        sourceId: source.budget
        path: raw/budget.md
        lines: "12-18"
        weight: 1.0
        confidence: 0.9
---

## Compiled Truth
Budget details.
"""
    claims = parse_claims_from_content(content)
    assert len(claims) == 1
    assert claims[0].id == "claim.budget.q3"
    assert claims[0].text == "Q3 budget is 50M"
    assert claims[0].status == "supported"
    assert len(claims[0].evidence) == 1
    assert claims[0].evidence[0].path == "raw/budget.md"
    assert claims[0].evidence[0].lines == "12-18"


def test_parse_claims_from_content_empty_when_missing() -> None:
    content = "---\ntype: concept\n---\n\n## Compiled Truth\nBody.\n"
    assert parse_claims_from_content(content) == ()


def test_ensure_compile_claims_adds_fallback_when_missing() -> None:
    content = "---\ntype: concept\nsources:\n  - notes.md\n---\n\n## Compiled Truth\nBudget is 50M for Q3.\n"
    merged = ensure_compile_claims(content, "Finance/Budget", ["notes.md"])
    claims = parse_claims_from_content(merged)
    assert len(claims) == 1
    assert "50M" in claims[0].text
    assert claims[0].status == "unknown"
    assert claims[0].evidence[0].path == "notes.md"


def test_ensure_compile_claims_pins_content_sha256(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "budget.md"
    raw_bytes = b"Budget is 50M for Q3."
    raw_file.write_bytes(raw_bytes)

    content = """---
type: concept
claims:
  - id: claim.budget.q3
    text: Q3 budget is 50M
    status: supported
    evidence:
      - kind: raw-note
        path: raw/budget.md
---
Body
"""
    merged = ensure_compile_claims(content, "Finance/Budget", ["budget.md"], structure=structure)
    claims = parse_claims_from_content(merged)
    assert len(claims) == 1
    evidence = claims[0].evidence[0]
    assert evidence.content_sha256 == hashlib.sha256(raw_bytes).hexdigest()
    assert evidence.updated_at


def test_resolve_evidence_snapshot_status_tri_state(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "budget.md"
    raw_bytes = b"Budget is 50M"
    raw_file.write_bytes(raw_bytes)
    pinned = hashlib.sha256(raw_bytes).hexdigest()

    from myrm_agent_harness.toolkits.wiki.core.claims_contract import resolve_evidence_snapshot_status

    assert resolve_evidence_snapshot_status("raw/budget.md", pinned, structure) == "verified"
    raw_file.write_bytes(b"Budget changed")
    assert resolve_evidence_snapshot_status("raw/budget.md", pinned, structure) == "stale"
    assert resolve_evidence_snapshot_status("raw/budget.md", "", structure) == "missing"
    assert resolve_evidence_snapshot_status("raw/missing.md", pinned, structure) == "missing"


def test_format_resource_uri_normalizes_path_and_digest() -> None:
    sha = "abc123"
    assert format_resource_uri("budget.md", sha) == f"raw/budget.md@sha256:{sha}"
    assert format_resource_uri("raw/budget.md", sha) == f"raw/budget.md@sha256:{sha}"
    assert format_resource_uri("", sha) == ""
    assert format_resource_uri("raw/budget.md", "") == ""


def test_collect_raw_content_hashes_uses_relative_keys(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "notes.md"
    raw_bytes = b"Portable hash key"
    raw_file.write_bytes(raw_bytes)
    expected_sha = hashlib.sha256(raw_bytes).hexdigest()

    hashes = collect_raw_content_hashes(structure)
    assert hashes == {"raw/notes.md": expected_sha}


def test_record_and_lookup_raw_supersede_uri(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    previous_sha = "deadbeef" * 8
    new_sha = "cafebabe" * 8

    record_raw_supersede_entry(
        structure,
        rel_path="budget.md",
        previous_sha256=previous_sha,
        new_sha256=new_sha,
        reason="settings import",
    )

    uri = lookup_raw_supersede_uri(structure, "raw/budget.md")
    assert uri == f"raw/budget.md@sha256:{previous_sha}"

    metadata_path = structure.get_wiki_metadata_path()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    entry = metadata[RAW_SUPERSEDE_KEY]["raw/budget.md"]
    assert entry["current_sha256"] == new_sha
    assert entry["reason"] == "settings import"


def test_build_evidence_resource_uri_prefers_pin(tmp_path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    raw_file = structure.raw_dir / "budget.md"
    raw_bytes = b"Live content"
    raw_file.write_bytes(raw_bytes)
    live_sha = hashlib.sha256(raw_bytes).hexdigest()
    pinned_sha = "pinned" * 8

    assert build_evidence_resource_uri("raw/budget.md", pinned_sha, structure=structure) == (
        f"raw/budget.md@sha256:{pinned_sha}"
    )
    assert build_evidence_resource_uri("raw/budget.md", "", structure=structure) == (f"raw/budget.md@sha256:{live_sha}")


def test_validate_compile_claims_rejects_empty_entries() -> None:
    content = """---
type: concept
claims:
  - id: ""
    text: ""
    status: supported
---
Body
"""
    parsed = parse_claims_from_content(content)
    assert validate_compile_claims(parsed) is False
