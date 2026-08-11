"""Map wiki lint issue types to user-facing action kinds for health reports.

[INPUT]
- issue_type: wiki lint 问题类型字符串

[OUTPUT]
- WikiIssueActionKind: Literal 类型（repair / recompile / navigate / info）
- issue_action_kind(): issue_type → action kind 映射

[POS]
Translation layer between internal wiki lint diagnostics and the user-facing
action vocabulary used in wiki health reports.
"""

from __future__ import annotations

from typing import Literal

WikiIssueActionKind = Literal["repair", "recompile", "navigate", "info"]

_ISSUE_TYPE_ACTION: dict[str, WikiIssueActionKind] = {
    "invalid_frontmatter_type": "repair",
    "stale": "recompile",
    "drift": "navigate",
    "broken_link": "navigate",
    "broken_wikilink": "navigate",
    "incomplete": "navigate",
    "knowledge_gap": "navigate",
    "provenance_gap": "navigate",
    "security_redacted": "info",
    "security_removed": "info",
}


def action_kind_for_issue_type(issue_type: str) -> WikiIssueActionKind:
    """Return the primary user action for a lint issue type."""
    return _ISSUE_TYPE_ACTION.get(issue_type, "info")


def count_open_actions(issues: list[object]) -> int:
    """Count issues that require user or guided action (excludes informational only)."""
    total = 0
    for issue in issues:
        action_kind = getattr(issue, "action_kind", None)
        if action_kind is None:
            issue_type = getattr(issue, "issue_type", "")
            action_kind = action_kind_for_issue_type(str(issue_type))
        if action_kind != "info":
            total += 1
    return total
