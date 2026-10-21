"""Deterministic wiki structural lint — SSOT for broken links and frontmatter gates.

[INPUT]
- ..core.structure::WikiStructure (POS: vault paths)
- ..core.link_extraction::extract_markdown_link_targets, extract_wikilink_targets (POS: link syntax SSOT shared with graph edges)
- ..core.link_resolver::WikiLinkResolver, concept_link_name (POS: link target resolution SSOT shared with graph edges; names the pages an ambiguous target matches)
- ..core.frontmatter_contract::validate_wiki_frontmatter (POS: type enum gate)
- ..core.types::LintIssue (POS: shared lint issue model)

[OUTPUT]
- StructuralLintSnapshot: aggregate counts for product stats surfaces
- collect_broken_link_issues: scans and returns broken markdown link issues
- collect_broken_wikilink_issues: scans and returns broken Obsidian wikilink issues; a link that names several pages equally well says which
- collect_invalid_frontmatter_type_issues: scans and returns invalid frontmatter type issues
- collect_provenance_gap_issues: scans and returns provenance gap issues

[POS]
Zero-LLM structural lint SSOT. Used by WikiLinter and server /wiki/stats without
triggering LLM maintenance paths.

Scope: markdown `[text](path)` links and Obsidian `[[wikilink]]` targets resolved by
`core.link_resolver.WikiLinkResolver` (page paths, frontmatter `title` / aliases /
`canonical_id`, bare file names) or, for read-only federated public mounts, by
`WikiStructure.resolve_concept_file_path`, and raw-backed provenance (`sources` +
`provenance`) for local concept pages.
Links are read by `core.link_extraction`: code is skipped, and external URLs and same-page
anchors are not vault paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    WikiProvenance,
    load_frontmatter_metadata,
    validate_wiki_frontmatter,
)
from myrm_agent_harness.toolkits.wiki.core.link_extraction import (
    extract_markdown_link_targets,
    extract_wikilink_targets,
)
from myrm_agent_harness.toolkits.wiki.core.link_resolver import WikiLinkResolver, concept_link_name
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import LintIssue
from myrm_agent_harness.toolkits.wiki.maintenance.issue_kind import (
    action_kind_for_issue_type,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_AMBIGUOUS_PAGES_SHOWN = 5
_AUTHOR_PROVENANCE: frozenset[str] = frozenset(
    {
        WikiProvenance.AGENT.value,
        WikiProvenance.CREATE_NOTE.value,
        WikiProvenance.CHAT_SAVE.value,
        WikiProvenance.CHAT_COMPOUND.value,
        WikiProvenance.CONTRADICTION_SYNTHESIS.value,
    }
)
_RAW_BACKED_PROVENANCE: frozenset[str] = frozenset(
    {
        WikiProvenance.COMPILED.value,
        WikiProvenance.REPAIRED.value,
        WikiProvenance.IMPORT.value,
        WikiProvenance.WEB_FETCH.value,
    }
)


@dataclass(frozen=True, slots=True)
class StructuralLintSnapshot:
    """Aggregate deterministic lint counts for GUI/API surfaces."""

    broken_links: int
    invalid_frontmatter_types: int
    provenance_gaps: int
    scanned_concepts: int

    def has_issues(self) -> bool:
        return self.broken_links > 0 or self.invalid_frontmatter_types > 0 or self.provenance_gaps > 0


def collect_broken_link_issues(structure: WikiStructure) -> list[LintIssue]:
    """Check concept articles for broken relative markdown links."""
    issues: list[LintIssue] = []
    for concept_path in structure.list_concepts():
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to check links in %s: %s", concept_path, exc)
            continue

        for link_target in extract_markdown_link_targets(content):
            target_path = (concept_path.parent / link_target).resolve()
            if not target_path.exists():
                issues.append(
                    LintIssue(
                        issue_type="broken_link",
                        severity="medium",
                        location=str(concept_path),
                        description=f"Broken link to {link_target}",
                        action_kind=action_kind_for_issue_type("broken_link"),
                        can_auto_fix=False,
                    )
                )
    return issues


def _wikilink_resolves(structure: WikiStructure, resolver: WikiLinkResolver, target: str, source: str | None) -> bool:
    """Whether a wikilink names a local page the graph links too, or a federated public page."""
    if resolver.resolve(target, source) is not None:
        return True
    public_page = structure.resolve_concept_file_path(target)
    return public_page is not None and not public_page.is_relative_to(structure.concepts_dir)


def _broken_wikilink_description(resolver: WikiLinkResolver, target: str, source: str | None) -> str:
    """Tell a link that names no page from one that names several equally well."""
    pages = resolver.ambiguous_pages(target, source)
    if not pages:
        return f"Broken wikilink to [[{target}]]"
    shown = ", ".join(pages[:_AMBIGUOUS_PAGES_SHOWN])
    more = len(pages) - _AMBIGUOUS_PAGES_SHOWN
    return f"Ambiguous wikilink [[{target}]] matches {shown}" + (f" and {more} more" if more > 0 else "")


def collect_broken_wikilink_issues(structure: WikiStructure) -> list[LintIssue]:
    """Check concept articles for broken Obsidian wikilink targets."""
    issues: list[LintIssue] = []
    resolver = WikiLinkResolver(structure)
    for concept_path in structure.list_concepts():
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to check wikilinks in %s: %s", concept_path, exc)
            continue

        source = (
            concept_link_name(concept_path, structure.concepts_dir)
            if concept_path.is_relative_to(structure.concepts_dir)
            else None
        )
        for target in extract_wikilink_targets(content):
            if not _wikilink_resolves(structure, resolver, target, source):
                issues.append(
                    LintIssue(
                        issue_type="broken_wikilink",
                        severity="medium",
                        location=str(concept_path),
                        description=_broken_wikilink_description(resolver, target, source),
                        action_kind=action_kind_for_issue_type("broken_wikilink"),
                        can_auto_fix=False,
                    )
                )
    return issues


def _sources_from_metadata(metadata: dict[str, object]) -> list[str]:
    raw = metadata.get("sources")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _normalize_raw_source_path(source: str) -> str:
    normalized = source.strip().replace("\\", "/")
    if normalized.startswith("raw/"):
        return normalized[4:]
    return normalized


def _raw_source_exists(structure: WikiStructure, source: str) -> bool:
    if source.startswith("http://") or source.startswith("https://"):
        return True
    try:
        return structure.get_raw_file_path(_normalize_raw_source_path(source)).is_file()
    except ValueError:
        return False


def _is_local_concept(structure: WikiStructure, concept_path: Path) -> bool:
    try:
        concept_path.relative_to(structure.concepts_dir)
        return True
    except ValueError:
        return False


def collect_provenance_gap_issues(structure: WikiStructure) -> list[LintIssue]:
    """Flag concept pages missing raw-backed provenance or pointing at missing raw files."""
    issues: list[LintIssue] = []
    for concept_path in structure.list_concepts():
        if not _is_local_concept(structure, concept_path):
            continue
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to check provenance for %s: %s", concept_path, exc)
            continue

        metadata, _body = load_frontmatter_metadata(content)
        provenance_raw = metadata.get("provenance")
        provenance = str(provenance_raw).strip().lower() if provenance_raw is not None else ""
        if provenance in _AUTHOR_PROVENANCE:
            continue

        sources = _sources_from_metadata(metadata)
        if not sources:
            issues.append(
                LintIssue(
                    issue_type="provenance_gap",
                    severity=("medium" if provenance in _RAW_BACKED_PROVENANCE else "high"),
                    location=str(concept_path),
                    description=(
                        "Missing sources list for a raw-backed concept page"
                        if provenance in _RAW_BACKED_PROVENANCE
                        else (
                            "Missing provenance and sources metadata"
                            if not provenance
                            else f"Missing sources list for provenance '{provenance}'"
                        )
                    ),
                    action_kind=action_kind_for_issue_type("provenance_gap"),
                    can_auto_fix=False,
                    suggested_fix="Recompile from raw sources or restore frontmatter provenance",
                )
            )
            continue

        missing_sources = [source for source in sources if not _raw_source_exists(structure, source)]
        if missing_sources:
            missing_label = ", ".join(missing_sources[:3])
            if len(missing_sources) > 3:
                missing_label = f"{missing_label}, +{len(missing_sources) - 3} more"
            issues.append(
                LintIssue(
                    issue_type="provenance_gap",
                    severity="high",
                    location=str(concept_path),
                    description=f"Sources not found in raw vault: {missing_label}",
                    action_kind=action_kind_for_issue_type("provenance_gap"),
                    can_auto_fix=False,
                    suggested_fix="Restore the raw source file or recompile this concept",
                )
            )
    return issues


def collect_invalid_frontmatter_type_issues(
    structure: WikiStructure,
) -> list[LintIssue]:
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
                action_kind=action_kind_for_issue_type("invalid_frontmatter_type"),
                can_auto_fix=True,
                suggested_fix="Repair page metadata to add a valid page type",
            )
        )
    return issues


def collect_structural_lint_issues(structure: WikiStructure) -> list[LintIssue]:
    """Return deterministic structural lint issues for a vault (zero LLM)."""
    return [
        *collect_broken_link_issues(structure),
        *collect_broken_wikilink_issues(structure),
        *collect_invalid_frontmatter_type_issues(structure),
        *collect_provenance_gap_issues(structure),
    ]


def collect_structural_lint_snapshot(
    structure: WikiStructure,
) -> StructuralLintSnapshot:
    """Return aggregate structural lint counts for a vault."""
    concepts = structure.list_concepts()
    broken_links = collect_broken_link_issues(structure)
    broken_wikilinks = collect_broken_wikilink_issues(structure)
    invalid_types = collect_invalid_frontmatter_type_issues(structure)
    provenance_gaps = collect_provenance_gap_issues(structure)
    return StructuralLintSnapshot(
        broken_links=len(broken_links) + len(broken_wikilinks),
        invalid_frontmatter_types=len(invalid_types),
        provenance_gaps=len(provenance_gaps),
        scanned_concepts=len(concepts),
    )
