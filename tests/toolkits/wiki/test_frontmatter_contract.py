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
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer


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
    ["source", "entity", "concept", "comparison", "overview", "question", "session", "metric"],
)
def test_validate_accepts_allowed_types(page_type: str) -> None:
    content = f"---\ntype: {page_type}\n---\n\n# Title"
    result = validate_wiki_frontmatter(content)
    assert result.ok is True
    assert result.page_type == page_type


def test_infer_type_for_raw_import_defaults_to_source() -> None:
    inferred = infer_type_for_import("notes/meeting.md", {}, is_raw_import=True)
    assert inferred == WikiPageType.SOURCE


def test_infer_type_for_metric() -> None:
    inferred = infer_type_for_import("metrics/gmv.md", {}, is_raw_import=False)
    assert inferred == WikiPageType.METRIC


def test_validate_metric_frontmatter() -> None:
    # Valid metric frontmatter
    content = (
        "---\n"
        "type: metric\n"
        "formula: sum(revenue)\n"
        "unit: USD\n"
        "source_systems:\n"
        "  - sap\n"
        "  - erp\n"
        "verification_rule: revenue >= 0\n"
        "---\n\n"
        "# GMV"
    )
    result = validate_wiki_frontmatter(content)
    assert result.ok is True
    assert result.page_type == "metric"

    # Invalid metric types
    bad_content = "---\ntype: metric\nformula: 123\nsource_systems: not_a_list\nunit: 456\nverification_rule: 789\n---\n\n# Bad"
    bad_result = validate_wiki_frontmatter(bad_content)
    assert bad_result.ok is False
    assert any("formula" in err for err in bad_result.errors)
    assert any("source_systems" in err for err in bad_result.errors)
    assert any("unit" in err for err in bad_result.errors)
    assert any("verification_rule" in err for err in bad_result.errors)


def test_validate_metric_frontmatter_edge_cases() -> None:
    # 1. Minimal metric page (optional fields omitted)
    minimal_content = "---\ntype: metric\n---\n\n# Basic Metric"
    res_minimal = validate_wiki_frontmatter(minimal_content)
    assert res_minimal.ok is True
    assert res_minimal.page_type == "metric"

    # 2. Empty source_systems list
    empty_sources_content = "---\ntype: metric\nsource_systems: []\n---\n\n# Empty Sources"
    res_empty_sources = validate_wiki_frontmatter(empty_sources_content)
    assert res_empty_sources.ok is True

    # 3. Non-string elements in source_systems
    mixed_sources = "---\ntype: metric\nsource_systems: ['sap', 123]\n---\n\n# Mixed Sources"
    res_mixed_sources = validate_wiki_frontmatter(mixed_sources)
    assert res_mixed_sources.ok is False
    assert any("source_systems" in err for err in res_mixed_sources.errors)

    # 4. Dict formula or boolean verification_rule
    complex_bad = "---\ntype: metric\nformula: {expr: 'x+y'}\nverification_rule: true\n---\n\n# Complex Bad"
    res_complex_bad = validate_wiki_frontmatter(complex_bad)
    assert res_complex_bad.ok is False
    assert any("formula" in err for err in res_complex_bad.errors)
    assert any("verification_rule" in err for err in res_complex_bad.errors)


def test_infer_type_for_import_all_branches() -> None:
    # Existing valid type in metadata
    assert infer_type_for_import("any/path.md", {"type": "concept"}) == WikiPageType.CONCEPT
    # Raw
    assert infer_type_for_import("raw/note.md", {}, is_raw_import=True) == WikiPageType.SOURCE
    # Metric
    assert infer_type_for_import("metrics/gmv.md", {}, is_raw_import=False) == WikiPageType.METRIC
    # Comparison
    assert infer_type_for_import("comparisons/a_vs_b.md", {}, is_raw_import=False) == WikiPageType.COMPARISON
    # Question
    assert infer_type_for_import("questions/faq.md", {}, is_raw_import=False) == WikiPageType.QUESTION
    # Entity
    assert infer_type_for_import("entities/user.md", {}, is_raw_import=False) == WikiPageType.ENTITY
    # Overview
    assert infer_type_for_import("folder/index.md", {}, is_raw_import=False) == WikiPageType.OVERVIEW
    # Session
    assert infer_type_for_import("recent/log.md", {}, is_raw_import=False) == WikiPageType.SESSION
    # Default Concept
    assert infer_type_for_import("knowledge/general.md", {}, is_raw_import=False) == WikiPageType.CONCEPT


def test_ensure_draft_frontmatter_stamps_draft() -> None:
    from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import ensure_draft_frontmatter
    content = "---\ntype: concept\npublished_at: '2026-01-01'\n---\n# Title\n"
    draft = ensure_draft_frontmatter(content)
    assert "publish_status: draft" in draft
    assert "published_at" not in draft


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


def test_indexer_extracts_metric_source_systems_edges(tmp_path: Path) -> None:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    indexer = WikiIndexer(structure)

    metric_content = """---
type: metric
formula: "(rev - cost) / rev"
unit: "CNY/件"
source_systems:
  - sap_fi
  - wms_core
verification_rule: "rev > 0 and cost >= 0"
---
# Gross Margin
Calculated based on [[revenue]] and [[cogs]].
"""

    indexer.extract_and_upsert_edges("metrics/gross_margin", metric_content)
    outgoing = indexer.get_outgoing_edges("metrics/gross_margin")
    targets = {target for target, _weight in outgoing}

    assert "system:sap_fi" in targets
    assert "system:wms_core" in targets
    assert "revenue" in targets
    assert "cogs" in targets

