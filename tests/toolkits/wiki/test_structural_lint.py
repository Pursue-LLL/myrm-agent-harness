"""Tests for deterministic wiki structural lint SSOT."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import (
    collect_broken_link_issues,
    collect_broken_wikilink_issues,
    collect_invalid_frontmatter_type_issues,
    collect_structural_lint_issues,
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

    broken_wikilink = structure.get_concept_file_path("Broken Wikilink")
    broken_wikilink.write_text(
        "---\ntitle: Broken WL\ntype: concept\n---\n\nSee [[Missing Concept]] for details.",
        encoding="utf-8",
    )

    code_example = structure.get_concept_file_path("Code Example")
    code_example.write_text(
        "---\ntitle: Code\ntype: concept\n---\n\n```md\n[[Ignored In Fence]]\n```",
        encoding="utf-8",
    )

    markdown_fence = structure.get_concept_file_path("Markdown Fence")
    markdown_fence.write_text(
        "---\ntitle: Markdown Fence\ntype: concept\n---\n\n```md\n[Ignored Link](missing.md)\n```",
        encoding="utf-8",
    )

    invalid = structure.get_concept_file_path("Invalid Type")
    invalid.write_text("---\ntitle: Invalid\n---\n\nBody", encoding="utf-8")

    valid = structure.get_concept_file_path("Valid Concept")
    valid.write_text(
        "---\ntitle: Valid\ntype: concept\n---\n\n## Compiled Truth\nValid body.",
        encoding="utf-8",
    )

    fragment_link = structure.get_concept_file_path("Fragment Link")
    fragment_link.write_text(
        "---\ntitle: Fragment\ntype: concept\n---\n\nSee [[Valid Concept#Section]]",
        encoding="utf-8",
    )

    gravity = structure.get_concept_file_path("Gravity")
    gravity.write_text(
        "---\ntitle: 重力\ntype: concept\n---\n\n## Compiled Truth\nGravity body.",
        encoding="utf-8",
    )

    title_link = structure.get_concept_file_path("Title Link")
    title_link.write_text(
        "---\ntitle: Title Link\ntype: concept\n---\n\nSee [[重力]] for details.",
        encoding="utf-8",
    )
    return structure


def test_collect_broken_link_issues(wiki_structure: WikiStructure) -> None:
    issues = collect_broken_link_issues(wiki_structure)
    assert len(issues) == 1
    assert issues[0].issue_type == "broken_link"


def test_collect_broken_wikilink_issues(wiki_structure: WikiStructure) -> None:
    issues = collect_broken_wikilink_issues(wiki_structure)
    assert len(issues) == 1
    assert issues[0].issue_type == "broken_wikilink"


def test_collect_invalid_frontmatter_type_issues(wiki_structure: WikiStructure) -> None:
    issues = collect_invalid_frontmatter_type_issues(wiki_structure)
    assert len(issues) == 1
    assert issues[0].issue_type == "invalid_frontmatter_type"


def test_wikilink_with_fragment_resolves_valid_target(wiki_structure: WikiStructure) -> None:
    issues = collect_broken_wikilink_issues(wiki_structure)
    fragment_issues = [issue for issue in issues if "Fragment Link" in issue.location]
    assert fragment_issues == []


def test_wikilink_title_alias_resolves_frontmatter_title(wiki_structure: WikiStructure) -> None:
    issues = collect_broken_wikilink_issues(wiki_structure)
    title_link_issues = [issue for issue in issues if "Title Link" in issue.location]
    assert title_link_issues == []


def test_collect_structural_lint_snapshot(wiki_structure: WikiStructure) -> None:
    snapshot = collect_structural_lint_snapshot(wiki_structure)
    assert snapshot.scanned_concepts == 9
    assert snapshot.broken_links == 2
    assert snapshot.invalid_frontmatter_types == 1
    assert snapshot.has_issues() is True


def test_markdown_link_in_code_fence_is_ignored(wiki_structure: WikiStructure) -> None:
    issues = collect_broken_link_issues(wiki_structure)
    fence_issues = [issue for issue in issues if "Markdown Fence" in issue.location]
    assert fence_issues == []


def test_broken_link_skips_http_urls(wiki_structure: WikiStructure) -> None:
    external = wiki_structure.get_concept_file_path("External Link")
    external.write_text(
        "---\ntitle: External\ntype: concept\n---\n\n[Site](https://example.com/page)",
        encoding="utf-8",
    )

    issues = collect_broken_link_issues(wiki_structure)
    external_issues = [issue for issue in issues if "External Link" in issue.location]
    assert external_issues == []


def test_wikilink_target_with_md_suffix_resolves(wiki_structure: WikiStructure) -> None:
    target = wiki_structure.get_concept_file_path("Valid Concept")
    linker = wiki_structure.get_concept_file_path("Md Suffix Link")
    linker.write_text(
        "---\ntitle: Md Suffix\ntype: concept\n---\n\nSee [[Valid Concept.md]]",
        encoding="utf-8",
    )

    issues = collect_broken_wikilink_issues(wiki_structure)
    md_suffix_issues = [issue for issue in issues if "Md Suffix Link" in issue.location]
    assert md_suffix_issues == []
    assert target.is_file()


def test_collect_structural_lint_issues_merges_all_kinds(
    wiki_structure: WikiStructure,
) -> None:
    issues = collect_structural_lint_issues(wiki_structure)
    issue_types = {issue.issue_type for issue in issues}
    assert "broken_link" in issue_types
    assert "broken_wikilink" in issue_types
    assert "invalid_frontmatter_type" in issue_types


def test_invalid_frontmatter_type_skips_unreadable_concept(
    wiki_structure: WikiStructure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    locked_path = wiki_structure.get_concept_file_path("Locked Type")
    locked_path.write_text("---\ntitle: Locked\n---\n\nBody", encoding="utf-8")

    original_read_text = Path.read_text

    def _read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.resolve() == locked_path.resolve():
            raise OSError("permission denied")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", _read_text)

    issues = collect_invalid_frontmatter_type_issues(wiki_structure)
    locked_issues = [issue for issue in issues if str(locked_path) in issue.location]
    assert locked_issues == []
