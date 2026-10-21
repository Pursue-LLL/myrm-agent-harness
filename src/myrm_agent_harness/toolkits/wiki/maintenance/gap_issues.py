"""Knowledge-gap lint issues derived from graph insights.

[INPUT]
- collections.abc::Callable (POS: type hints)
- myrm_agent_harness.toolkits.wiki.core.link_resolver::concept_page_exists (POS: page-key presence check)
- myrm_agent_harness.toolkits.wiki.core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- myrm_agent_harness.toolkits.wiki.core.types::LintIssue (POS: Wiki toolkit type definition center)
- myrm_agent_harness.toolkits.wiki.maintenance.issue_kind::action_kind_for_issue_type (POS: user-facing action vocabulary)

[OUTPUT]
- knowledge_gap_issues: lint issues for isolated and bridge pages

[POS]
Turns graph-insight knowledge gaps into lint issues. Insights also cover read-only public
mounts, so only gaps on pages of this vault, which a user can act on, are reported.
"""

from __future__ import annotations

from collections.abc import Callable

from myrm_agent_harness.toolkits.wiki.core.link_resolver import concept_page_exists
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.core.types import LintIssue
from myrm_agent_harness.toolkits.wiki.maintenance.issue_kind import action_kind_for_issue_type

_GAP_DESCRIPTIONS: dict[str, Callable[[dict[str, object]], str]] = {
    "isolated": lambda g: f"Isolated concept ({g.get('degree', 0)} connections)",
    "bridge": lambda g: f"Bridge node (connects {g.get('communities_connected', 0)} communities)",
}


def knowledge_gap_issues(structure: WikiStructure, insights: dict[str, list[dict[str, object]]]) -> list[LintIssue]:
    """Lint issues for the isolated/bridge gaps of ``insights`` that are pages of this vault."""
    issues: list[LintIssue] = []
    for gap in insights.get("knowledge_gaps", []):
        describe = _GAP_DESCRIPTIONS.get(str(gap.get("type", "")))
        if describe is None:
            continue
        node = str(gap["node"])
        if concept_page_exists(structure, node):
            issues.append(
                LintIssue(
                    issue_type="knowledge_gap",
                    severity="low",
                    location=node,
                    description=describe(gap),
                    action_kind=action_kind_for_issue_type("knowledge_gap"),
                )
            )
    return issues
