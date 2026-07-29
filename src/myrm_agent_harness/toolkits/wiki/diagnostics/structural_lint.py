"""Deterministic wiki structural lint — SSOT for broken links and frontmatter gates.

[INPUT]
..core.structure::WikiStructure (POS: vault paths)
..core.frontmatter_contract::validate_wiki_frontmatter (POS: type enum gate)
..core.types::LintIssue (POS: shared lint issue model)

[OUTPUT]
StructuralLintSnapshot: aggregate counts for product stats surfaces
collect_broken_link_issues, collect_broken_wikilink_issues, collect_invalid_frontmatter_type_issues
build_wikilink_title_index

[POS]
Zero-LLM structural lint SSOT. Used by WikiLinter and server /wiki/stats without
triggering LLM maintenance paths.

Scope: markdown `[text](path)` links and Obsidian `[[wikilink]]` targets resolved via
`WikiStructure.resolve_concept_file_path`, with frontmatter `title` / path-stem aliases.
Fenced/inline code blocks are skipped for both markdown links and wikilinks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.utils.markdown_frontmatter import parse_frontmatter
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import validate_wiki_frontmatter
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import LintIssue
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^\)]+)\)")
_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
_FENCED_OR_INLINE_CODE_PATTERN = re.compile(r"```[\s\S]*?```|`[^`\n]+`")


def _content_without_code_blocks(content: str) -> str:
    """Strip fenced and inline code so example wikilinks are not linted."""
    return _FENCED_OR_INLINE_CODE_PATTERN.sub("", content)


def _normalize_wikilink_target(raw_target: str) -> str:
    target = raw_target.split("|", maxsplit=1)[0].strip()
    if "#" in target:
        target = target.split("#", maxsplit=1)[0].strip()
    if target.lower().endswith(".md"):
        return target[:-3]
    return target


def _normalize_lookup_key(key: str) -> str:
    return key.strip().casefold()


def _concept_link_name(concept_path: Path, concepts_dir: Path) -> str:
    rel = concept_path.relative_to(concepts_dir)
    return str(rel.with_suffix("")).replace("\\", "/")


def build_wikilink_title_index(structure: WikiStructure) -> dict[str, str]:
    """Map normalized title or path-stem keys to unique concept path slugs."""
    candidates: dict[str, list[str]] = {}
    for concept_path in structure.list_concepts():
        link_name = _concept_link_name(concept_path, structure.concepts_dir)
        keys = {_normalize_lookup_key(link_name)}
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to index wikilink titles for %s: %s", concept_path, exc)
            continue

        metadata, _body = parse_frontmatter(content)
        title = metadata.get("title")
        if isinstance(title, str) and title.strip():
            keys.add(_normalize_lookup_key(title.strip()))

        for key in keys:
            candidates.setdefault(key, []).append(link_name)

    unique: dict[str, str] = {}
    for key, link_names in candidates.items():
        if len(link_names) == 1:
            unique[key] = link_names[0]
    return unique


def _wikilink_target_exists(
    structure: WikiStructure,
    target: str,
    title_index: dict[str, str],
) -> bool:
    if structure.resolve_concept_file_path(target) is not None:
        return True
    resolved_path = title_index.get(_normalize_lookup_key(target))
    if resolved_path is None:
        return False
    return structure.resolve_concept_file_path(resolved_path) is not None


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

        scan_content = _content_without_code_blocks(content)
        for _link_text, link_target in _MARKDOWN_LINK_PATTERN.findall(scan_content):
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


def collect_broken_wikilink_issues(structure: WikiStructure) -> list[LintIssue]:
    """Check concept articles for broken Obsidian wikilink targets."""
    issues: list[LintIssue] = []
    title_index = build_wikilink_title_index(structure)
    for concept_path in structure.list_concepts():
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to check wikilinks in %s: %s", concept_path, exc)
            continue

        scan_content = _content_without_code_blocks(content)
        for raw_target in _WIKILINK_PATTERN.findall(scan_content):
            target = _normalize_wikilink_target(raw_target)
            if not target or target.startswith("http"):
                continue
            if not _wikilink_target_exists(structure, target, title_index):
                issues.append(
                    LintIssue(
                        issue_type="broken_wikilink",
                        severity="medium",
                        location=str(concept_path),
                        description=f"Broken wikilink to [[{target}]]",
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
    broken_wikilinks = collect_broken_wikilink_issues(structure)
    invalid_types = collect_invalid_frontmatter_type_issues(structure)
    return StructuralLintSnapshot(
        broken_links=len(broken_links) + len(broken_wikilinks),
        invalid_frontmatter_types=len(invalid_types),
        scanned_concepts=len(concepts),
    )
