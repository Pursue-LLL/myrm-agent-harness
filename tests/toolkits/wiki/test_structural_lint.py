"""Tests for deterministic wiki structural lint SSOT."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import (
    collect_broken_link_issues,
    collect_invalid_frontmatter_type_issues,
    collect_structural_lint_snapshot,
)


@pytest.fixture
def wiki_structure(tmp_path: Path) -> WikiStructure:
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()

    broken = structure.get_concept_file_path("Broken Links")
    broken.write_text(
        "---\ntitle: Broken\ntype: concept\n---\n\n[Missing](missing.md)",
        encoding="utf-8",
    )

    invalid = structure.get_concept_file_path("Invalid Type")
    invalid.write_text("---\ntitle: Invalid\n---\n\nBody", encoding="utf-8")

    valid = structure.get_concept_file_path("Valid Concept")
    valid.write_text(
        "---\ntitle: Valid\ntype: concept\n---\n\n## Compiled Truth\nValid body.",
        encoding="utf-8",
    )
    return structure


def test_collect_broken_link_issues(wiki_structure: WikiStructure) -> None:
    issues = collect_broken_link_issues(wiki_structure)
    assert len(issues) == 1
    assert issues[0].issue_type == "broken_link"


def test_collect_invalid_frontmatter_type_issues(wiki_structure: WikiStructure) -> None:
    issues = collect_invalid_frontmatter_type_issues(wiki_structure)
    assert len(issues) == 1
    assert issues[0].issue_type == "invalid_frontmatter_type"


def test_collect_structural_lint_snapshot(wiki_structure: WikiStructure) -> None:
    snapshot = collect_structural_lint_snapshot(wiki_structure)
    assert snapshot.scanned_concepts == 3
    assert snapshot.broken_links == 1
    assert snapshot.invalid_frontmatter_types == 1
    assert snapshot.has_issues() is True
