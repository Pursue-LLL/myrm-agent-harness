"""Lowest Common Ancestor (LCA) delta branch summarization engine.

[INPUT]
- agent.context_management.branch_projection.branch_projection_types::BranchSummary, EntryKind, SessionEntry (POS:
  Types and data contracts for dual-track session tree and dynamic branch projection.)

[OUTPUT]
- find_lca: Find lowest common ancestor between two tree entry nodes.
- collect_departed_entries: Gather entries along the departed branch up to LCA.
- synthesize_branch_delta_summary: Extract key decisions, blockers, and file manifests.

[POS]
LCA branch discovery and delta summarization for lossless cross-branch transitions.
"""

from __future__ import annotations

import re
from typing import Mapping, Sequence

from .branch_projection_types import BranchSummary, EntryKind, SessionEntry

# Regex heuristics for file manifests mentioned in tool invocations or payloads
_FILE_PATH_PATTERN = re.compile(
    r"(?:(?:read|view|edit|write|file|path)[:=]\s*|[\"'])([\w\-./\\]+\.[a-zA-Z0-9_]+)[\"']?",
    re.IGNORECASE,
)


def find_lca(
    entries: Mapping[str, SessionEntry],
    entry_a_id: str,
    entry_b_id: str,
) -> str | None:
    """Find the Lowest Common Ancestor (LCA) entry between two tree nodes.

    Traverses parent pointers upward from entry_a to collect the ancestor set,
    then walks upward from entry_b to find the first common intersection.
    Time complexity: O(depth_a + depth_b).
    """
    if entry_a_id == entry_b_id:
        return entry_a_id

    ancestors_a: set[str] = set()
    curr_a: str | None = entry_a_id
    while curr_a is not None:
        ancestors_a.add(curr_a)
        node_a = entries.get(curr_a)
        curr_a = node_a.parent_id if node_a else None

    curr_b: str | None = entry_b_id
    while curr_b is not None:
        if curr_b in ancestors_a:
            return curr_b
        node_b = entries.get(curr_b)
        curr_b = node_b.parent_id if node_b else None

    return None


def collect_departed_entries(
    entries: Mapping[str, SessionEntry],
    from_leaf_id: str,
    lca_id: str,
) -> tuple[SessionEntry, ...]:
    """Collect entries along the departed branch up to (excluding) the LCA node.

    Returns the entries ordered chronologically from oldest (child of LCA)
    to newest (the leaf node).
    """
    departed: list[SessionEntry] = []
    curr: str | None = from_leaf_id

    while curr is not None and curr != lca_id:
        node = entries.get(curr)
        if node is None:
            break
        departed.append(node)
        curr = node.parent_id

    # Reverse to restore chronological order (ancestor -> descendant)
    departed.reverse()
    return tuple(departed)


def synthesize_branch_delta_summary(
    departed_entries: Sequence[SessionEntry],
    source_branch_id: str,
    target_branch_id: str,
    lca_entry_id: str,
) -> BranchSummary:
    """Extract decisions, blockers, and file manifests into a structured BranchSummary.

    Allows the destination branch to seamlessly inherit experience and file touched
    without carrying redundant or conflicting conversation turns.
    """
    read_files_set: set[str] = set()
    modified_files_set: set[str] = set()
    decisions: list[str] = []
    blockers: list[str] = []

    for entry in departed_entries:
        payload = entry.payload
        content = payload.get("content", "")
        role = payload.get("role", "")
        tool_name = payload.get("tool_name", "")
        error = payload.get("error") or payload.get("error_message")

        # Capture explicit or inferred file manifests
        if "read_file" in tool_name.lower() or "view" in tool_name.lower():
            for m in _FILE_PATH_PATTERN.finditer(content):
                read_files_set.add(m.group(1))
        elif "write" in tool_name.lower() or "edit" in tool_name.lower():
            for m in _FILE_PATH_PATTERN.finditer(content):
                modified_files_set.add(m.group(1))

        # Check explicit file manifests in metadata
        if "read_files" in entry.metadata:
            for f in entry.metadata["read_files"].split(","):
                clean = f.strip()
                if clean:
                    read_files_set.add(clean)
        if "modified_files" in entry.metadata:
            for f in entry.metadata["modified_files"].split(","):
                clean = f.strip()
                if clean:
                    modified_files_set.add(clean)

        # Detect decisions or key planning conclusions
        if role == "assistant" and any(
            kw in content.lower() for kw in ("decided", "decision:", "strategy:", "approach:")
        ):
            first_line = content.splitlines()[0][:120].strip()
            decisions.append(first_line)

        # Detect failures and blockers
        if error:
            blockers.append(error.strip()[:150])
        elif "error" in content.lower() or "failed" in content.lower():
            for line in content.splitlines():
                if any(kw in line.lower() for kw in ("error:", "exception:", "failed:")):
                    blockers.append(line.strip()[:150])
                    break

    read_files = tuple(sorted(read_files_set))
    modified_files = tuple(sorted(modified_files_set))
    key_decisions = tuple(decisions[:5])
    top_blockers = tuple(blockers[:5])
    departed_ids = tuple(e.entry_id for e in departed_entries)

    # Render structured summary text
    summary_lines = [
        f"### Branch Exploration Summary ({source_branch_id} -> {target_branch_id})",
        f"- **LCA Anchor Entry**: {lca_entry_id}",
        f"- **Departed Steps**: {len(departed_entries)} entries traversed",
    ]
    if read_files:
        summary_lines.append(f"- **Files Read**: {', '.join(read_files)}")
    if modified_files:
        summary_lines.append(f"- **Files Modified**: {', '.join(modified_files)}")
    if key_decisions:
        summary_lines.append("- **Key Decisions**:")
        for d in key_decisions:
            summary_lines.append(f"  * {d}")
    if top_blockers:
        summary_lines.append("- **Blockers / Lessons Learned**:")
        for b in top_blockers:
            summary_lines.append(f"  * {b}")

    summary_text = "\n".join(summary_lines)

    return BranchSummary(
        source_branch_id=source_branch_id,
        target_branch_id=target_branch_id,
        lca_entry_id=lca_entry_id,
        departed_entry_ids=departed_ids,
        read_files=read_files,
        modified_files=modified_files,
        key_decisions=key_decisions,
        blockers=top_blockers,
        summary_text=summary_text,
    )
