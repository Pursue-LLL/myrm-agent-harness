"""Deterministic wiki structural lint — SSOT for broken links and frontmatter gates.

[INPUT]
..core.structure::WikiStructure (POS: vault paths)
..core.frontmatter_contract::validate_wiki_frontmatter (POS: type enum gate)
..core.types::LintIssue (POS: shared lint issue model)

[OUTPUT]
StructuralLintSnapshot: aggregate counts for product stats surfaces
collect_broken_link_issues, collect_invalid_frontmatter_type_issues

[POS]
Zero-LLM structural lint SSOT. Used by WikiLinter and server /wiki/stats without
triggering LLM maintenance paths.

Scope: markdown `[text](path)` links only (same as legacy linter); Obsidian `[[wikilink]]`
resolution remains in indexer graph paths, not this counter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import validate_wiki_frontmatter
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import LintIssue
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^\)]+)\)")


@dataclass(frozen=True, slots=True)
class StructuralLintSnapshot:
    """Aggregate deterministic lint counts for GUI/API surfaces."""

    broken_links: int
    invalid_frontmatter_types: int
    scanned_concepts: int

    def has_issues(self) -> bool:
        return self.broken_links > 0 or self.invalid_frontmatter_types > 0


def collect_broken_link_issues(structure: WikiStructure) -> list[LintIssue]:
    """Check concept articles for broken relative markdown links."""
    issues: list[LintIssue] = []
    for concept_path in structure.list_concepts():
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to check links in %s: %s", concept_path, exc)
            continue

        for _link_text, link_target in _MARKDOWN_LINK_PATTERN.findall(content):
            if link_target.startswith("http"):
                continue
            target_path = (concept_path.parent / link_target).resolve()
            if not target_path.exists():
                issues.append(
                    LintIssue(
                        issue_type="broken_link",
                        severity="medium",
                        location=str(concept_path),
                        description=f"Broken link to {link_target}",
                        can_auto_fix=False,
                    )
                )
    return issues


def collect_invalid_frontmatter_type_issues(structure: WikiStructure) -> list[LintIssue]:
    """Check concept articles for required frontmatter `type` field."""
    issues: list[LintIssue] = []
    for concept_path in structure.list_concepts():
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to check frontmatter type for %s: %s", concept_path, exc)
            continue

        validation = validate_wiki_frontmatter(content)
        if validation.ok:
            continue
        issues.append(
            LintIssue(
                issue_type="invalid_frontmatter_type",
                severity="high",
                location=str(concept_path),
                description="; ".join(validation.errors),
                can_auto_fix=True,
                suggested_fix="Repair page metadata to add a valid page type",
            )
        )
    return issues


def collect_structural_lint_snapshot(structure: WikiStructure) -> StructuralLintSnapshot:
    """Return aggregate structural lint counts for a vault."""
    concepts = structure.list_concepts()
    broken_links = collect_broken_link_issues(structure)
    invalid_types = collect_invalid_frontmatter_type_issues(structure)
    return StructuralLintSnapshot(
        broken_links=len(broken_links),
        invalid_frontmatter_types=len(invalid_types),
        scanned_concepts=len(concepts),
    )
