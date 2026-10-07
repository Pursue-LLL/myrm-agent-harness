"""Unit tests for append-only tree session storage and non-destructive branch navigation.

Verifies:
1. Append-only immutability of parentId-linked conversation tree.
2. Linearized ancestry path projection from root to leaf.
3. Lowest Common Ancestor (LCA) and branch divergence resolution.
4. Non-destructive branch navigation with automated branch exploration summary generation.
5. Multi-branch switching without data loss or historical truncation.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.branch_navigation_and_summary_engine import (
    BranchNavigationAndSummaryEngine,
)
from myrm_agent_harness.runtime.context.tree_session_storage import (
    TreeSessionStorage,
)
from myrm_agent_harness.runtime.context.tree_session_storage_types import (
    TreeEntry,
    TreeEntryKind,
)


def test_tree_storage_append_only_and_ancestry_projection() -> None:
    storage = TreeSessionStorage()

    # Append Root
    root = TreeEntry(
        entry_id="node_0",
        parent_id=None,
        kind=TreeEntryKind.MESSAGE,
        role="system",
        content="System instructions.",
    )
    storage.append_entry(root)

    # Append Child 1
    node1 = TreeEntry(
        entry_id="node_1",
        parent_id="node_0",
        kind=TreeEntryKind.MESSAGE,
        role="user",
        content="Please implement feature X.",
    )
    storage.append_entry(node1)

    # Append Child 2
    node2 = TreeEntry(
        entry_id="node_2",
        parent_id="node_1",
        kind=TreeEntryKind.MESSAGE,
        role="assistant",
        content="Understood, starting implementation.",
    )
    storage.append_entry(node2)

    assert storage.total_entries_count() == 3

    # Invariant: Cannot append duplicate entry_id (strictly append-only)
    with pytest.raises(KeyError):
        storage.append_entry(node1)

    # Invariant: Cannot append with non-existent parent_id
    with pytest.raises(ValueError):
        storage.append_entry(
            TreeEntry(
                entry_id="orphan_node",
                parent_id="ghost_parent",
                kind=TreeEntryKind.MESSAGE,
                role="user",
                content="Lost message.",
            )
        )

    # Ancestry projection from node_2 back to root
    path = storage.get_ancestor_path("node_2")
    assert [e.entry_id for e in path] == ["node_0", "node_1", "node_2"]


def test_lowest_common_ancestor_and_branch_divergence() -> None:
    storage = TreeSessionStorage()

    # Base trunk: root -> step1 -> step2
    storage.append_entry(
        TreeEntry("root", None, TreeEntryKind.MESSAGE, "system", "Base prompt")
    )
    storage.append_entry(
        TreeEntry("step1", "root", TreeEntryKind.MESSAGE, "user", "Task goal")
    )
    storage.append_entry(
        TreeEntry("step2", "step1", TreeEntryKind.MESSAGE, "assistant", "Initial plan")
    )

    # Branch A: step2 -> step3_a -> step4_a
    storage.append_entry(
        TreeEntry("step3_a", "step2", TreeEntryKind.TOOL_INVOCATION, "assistant", "Approach A with library X")
    )
    storage.append_entry(
        TreeEntry("step4_a", "step3_a", TreeEntryKind.MESSAGE, "assistant", "Approach A hit dependency conflict")
    )

    # Branch B: step2 -> step3_b -> step4_b
    storage.append_entry(
        TreeEntry("step3_b", "step2", TreeEntryKind.TOOL_INVOCATION, "assistant", "Approach B with standard library")
    )
    storage.append_entry(
        TreeEntry("step4_b", "step3_b", TreeEntryKind.MESSAGE, "assistant", "Approach B succeeded")
    )

    # LCA of step4_a and step4_b is step2
    lca = storage.find_lca("step4_a", "step4_b")
    assert lca is not None
    assert lca.entry_id == "step2"

    # Divergence of Branch A from Branch B perspective: [step3_a, step4_a]
    divergence_a = storage.get_branch_divergence("step4_a", "step4_b")
    assert [e.entry_id for e in divergence_a] == ["step3_a", "step4_a"]

    # Divergence of Branch B from Branch A perspective: [step3_b, step4_b]
    divergence_b = storage.get_branch_divergence("step4_b", "step4_a")
    assert [e.entry_id for e in divergence_b] == ["step3_b", "step4_b"]


def test_non_destructive_navigation_and_forking() -> None:
    storage = TreeSessionStorage()
    engine = BranchNavigationAndSummaryEngine(storage)

    # Build initial linear conversation
    storage.append_entry(
        TreeEntry("root", None, TreeEntryKind.MESSAGE, "system", "Agent system prompt")
    )
    storage.append_entry(
        TreeEntry("t1_user", "root", TreeEntryKind.MESSAGE, "user", "Create a cache middleware")
    )
    storage.append_entry(
        TreeEntry("t1_ast", "t1_user", TreeEntryKind.MESSAGE, "assistant", "Implementing Redis cache")
    )
    storage.append_entry(
        TreeEntry("t2_ast", "t1_ast", TreeEntryKind.TOOL_INVOCATION, "assistant", "Error: Redis connection failed")
    )

    # Set leaf pointer at t2_ast (dead end in branch A)
    engine.set_leaf_pointer("t2_ast", branch_tag="branch_redis")
    initial_proj = engine.project_current_view()
    assert [e.entry_id for e in initial_proj.path_entries] == [
        "root",
        "t1_user",
        "t1_ast",
        "t2_ast",
    ]

    # Non-destructive navigation: Roll back to t1_user to try an in-memory SQLite cache instead
    new_proj, summary_record = engine.navigate_to(
        target_entry_id="t1_user",
        target_branch_tag="branch_sqlite",
        auto_summarize_abandoned=True,
    )

    # Crucial check: old nodes t1_ast and t2_ast were NEVER deleted or truncated!
    assert storage.get_entry("t1_ast") is not None
    assert storage.get_entry("t2_ast") is not None
    assert storage.total_entries_count() == 5  # 4 initial nodes + 1 branch summary node

    # Check summary was generated and attached
    assert summary_record is not None
    assert summary_record.fork_point_id == "t1_user"
    assert summary_record.abandoned_leaf_id == "t2_ast"
    assert summary_record.abandoned_node_count == 2
    assert "Redis connection failed" in summary_record.summary_text

    # The new projection starts at root -> t1_user -> attached branch summary
    summary_node = new_proj.path_entries[-1]
    assert summary_node.kind == TreeEntryKind.BRANCH_SUMMARY
    assert summary_node.parent_id == "t1_user"

    # Now fork a fresh branch from summary_node
    new_fork_node = engine.fork_new_branch(
        from_entry_id=summary_node.entry_id,
        initial_content="Let's try SQLite memory cache instead.",
        role="user",
        branch_tag="branch_sqlite",
    )
    assert new_fork_node.parent_id == summary_node.entry_id
    assert engine.current_leaf_id == new_fork_node.entry_id

    # Switch back to the old branch t2_ast: zero data loss, everything intact!
    restored_proj, _ = engine.navigate_to(
        target_entry_id="t2_ast",
        target_branch_tag="branch_redis",
        auto_summarize_abandoned=False,
    )
    assert [e.entry_id for e in restored_proj.path_entries] == [
        "root",
        "t1_user",
        "t1_ast",
        "t2_ast",
    ]


def test_end_to_end_multi_branch_exploration_trajectory() -> None:
    storage = TreeSessionStorage()
    engine = BranchNavigationAndSummaryEngine(storage)

    # Root
    storage.append_entry(
        TreeEntry("e0", None, TreeEntryKind.MESSAGE, "system", "Instruction base")
    )
    engine.set_leaf_pointer("e0")

    # User input 1
    e1 = engine.fork_new_branch("e0", "Design architecture for service X", role="user")
    # Assistant response 1
    e2 = engine.fork_new_branch(e1.entry_id, "Proposing microservice mesh", role="assistant")
    # Tool call
    e3 = engine.fork_new_branch(
        e2.entry_id, "Profiling latency", role="assistant", kind=TreeEntryKind.TOOL_INVOCATION
    )

    proj = engine.project_current_view()
    assert proj.total_entries_count == 4
    assert [entry.entry_id for entry in proj.path_entries] == ["e0", e1.entry_id, e2.entry_id, e3.entry_id]
