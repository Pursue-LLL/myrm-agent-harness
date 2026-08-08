"""Tests for wiki frontmatter type gate contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.claims_contract import parse_claims_from_content
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    FrontmatterValidationError,
    WikiPageType,
    apply_compile_gate,
    infer_type_for_import,
    repair_file_frontmatter,
    repair_missing_types,
    validate_wiki_frontmatter,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.pending import WikiPendingEditsManager


def test_validate_rejects_missing_type() -> None:
    content = "# Title\n\nBody"
    result = validate_wiki_frontmatter(content)
    assert result.ok is False
    assert "type" in result.errors[0].lower()


def test_validate_rejects_invalid_type() -> None:
    content = "---\ntype: blogpost\n---\n\n# Title"
    result = validate_wiki_frontmatter(content)
    assert result.ok is False
    assert "invalid type" in result.errors[0].lower()


@pytest.mark.parametrize(
    "page_type",
    ["source", "entity", "concept", "comparison", "overview", "question", "session"],
)
def test_validate_accepts_allowed_types(page_type: str) -> None:
    content = f"---\ntype: {page_type}\n---\n\n# Title"
    result = validate_wiki_frontmatter(content)
    assert result.ok is True
    assert result.page_type == page_type


def test_infer_type_for_raw_import_defaults_to_source() -> None:
    inferred = infer_type_for_import("notes/meeting.md", {}, is_raw_import=True)
    assert inferred == WikiPageType.SOURCE


def test_apply_compile_gate_injects_concept_type() -> None:
    raw = "## Compiled Truth\n\nSummary"
    gated = apply_compile_gate(raw, "Programming/Rust", ["raw/rust.md"])
    result = validate_wiki_frontmatter(gated)
    assert result.ok is True
    assert result.page_type == "concept"


def test_repair_missing_types_updates_files(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()

    concept_path = structure.get_concept_file_path("demo/concept")
    concept_path.write_text("# Missing frontmatter", encoding="utf-8")

    raw_path = structure.get_raw_file_path("note.md")
    raw_path.write_text("Plain raw note", encoding="utf-8")

    result = repair_missing_types(structure)
    assert result.files_scanned == 2
    assert result.files_repaired == 2

    concept_validation = validate_wiki_frontmatter(concept_path.read_text(encoding="utf-8"))
    raw_validation = validate_wiki_frontmatter(raw_path.read_text(encoding="utf-8"))
    assert concept_validation.ok is True
    assert concept_validation.page_type == "concept"
    assert raw_validation.ok is True
    assert raw_validation.page_type == "source"


def test_repair_file_frontmatter_preserves_nested_claims(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    concept_path = structure.get_concept_file_path("Team/Budget")
    concept_path.parent.mkdir(parents=True, exist_ok=True)
    concept_path.write_text(
        """---
claims:
  - id: claim.budget.q3
    text: Q3 budget is 50M
    status: supported
    confidence: 0.9
    evidence:
      - kind: raw-source
        sourceId: source.budget
        path: raw/budget.md
        lines: ""
        weight: 1.0
        confidence: 0.8
---

## Compiled Truth
Budget.
""",
        encoding="utf-8",
    )

    repaired = repair_file_frontmatter(concept_path, is_raw_import=False, relative_path="Team/Budget")
    assert repaired is True

    claims = parse_claims_from_content(concept_path.read_text(encoding="utf-8"))
    assert len(claims) == 1
    assert claims[0].id == "claim.budget.q3"
    validation = validate_wiki_frontmatter(concept_path.read_text(encoding="utf-8"))
    assert validation.ok is True
    assert validation.page_type == "concept"


def test_apply_compile_gate_repairs_invalid_type() -> None:
    raw = "---\ntype: blogpost\n---\n\n## Compiled Truth"
    gated = apply_compile_gate(raw, "Demo", ["raw/demo.md"])
    result = validate_wiki_frontmatter(gated)
    assert result.ok is True
    assert result.page_type == "concept"


@pytest.mark.asyncio
async def test_pending_approve_blocks_invalid_type(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    pending_mgr = WikiPendingEditsManager(structure)

    edit_id = pending_mgr.add_pending_edit("demo/bad", "# No type frontmatter")
    with pytest.raises(FrontmatterValidationError):
        await pending_mgr.approve_edit(edit_id)

    valid_id = pending_mgr.add_pending_edit(
        "demo/good",
        "---\ntype: concept\n---\n\n# Good",
    )
    assert await pending_mgr.approve_edit(valid_id) is True
