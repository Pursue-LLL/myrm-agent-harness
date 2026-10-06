"""Tests for Session Tree Navigator and Time-Travel Branch Manager (Pi Harness v2)."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.runtime.context.session_tree_navigator import (
    NavigateTreeResult,
    SessionEntryType,
    SessionTreeNavigator,
    SessionTreeNode,
)


def test_append_linear_branch_and_leaf_tracking() -> None:
    """Test linear append operations with automatic parent chaining and leaf progression."""
    nav = SessionTreeNavigator()

    e1 = nav.append_entry(
        entry_type=SessionEntryType.MESSAGE,
        role="user",
        content="Hello world",
    )
    assert e1.parent_id is None
    assert nav.get_leaf_id() == e1.entry_id

    e2 = nav.append_entry(
        entry_type=SessionEntryType.MESSAGE,
        role="assistant",
        content="Hi there, how can I help?",
    )
    assert e2.parent_id == e1.entry_id
    assert nav.get_leaf_id() == e2.entry_id

    e3 = nav.append_entry(
        entry_type=SessionEntryType.MESSAGE,
        role="user",
        content="Show me current status",
    )
    assert e3.parent_id == e2.entry_id
    assert nav.get_leaf_id() == e3.entry_id

    # Branch inspection
    branch = nav.get_branch()
    assert len(branch) == 3
    assert [b.entry_id for b in branch] == [e1.entry_id, e2.entry_id, e3.entry_id]


def test_navigate_to_user_message_reverts_to_parent_and_extracts_editor_text() -> None:
    """Test time travel to user message: leaf reverts to parent and extracts text for edit-resend."""
    nav = SessionTreeNavigator()

    e1 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Step 1: Init")
    e2 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Step 1: Done")
    e3 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Step 2: Try flawed approach")
    e4 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Step 2: Failed with syntax error")

    assert nav.get_leaf_id() == e4.entry_id

    # Navigate back to user message e3
    res: NavigateTreeResult = nav.navigate_tree(e3.entry_id)
    assert res.is_noop is False
    assert res.target_id == e3.entry_id
    assert res.old_leaf_id == e4.entry_id
    # Critical invariant: leaf reverts to e3's parent (e2) so user can edit and resend
    assert res.new_leaf_id == e2.entry_id
    assert res.editor_text == "Step 2: Try flawed approach"
    assert nav.get_leaf_id() == e2.entry_id

    # Now append new corrected user action from e2
    e5 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Step 2: Try correct approach")
    assert e5.parent_id == e2.entry_id
    assert nav.get_leaf_id() == e5.entry_id

    # The active branch now is [e1, e2, e5]
    new_branch = nav.get_branch()
    assert [b.entry_id for b in new_branch] == [e1.entry_id, e2.entry_id, e5.entry_id]

    # Old abandoned nodes [e3, e4] still exist in tree
    assert nav.get_entry(e3.entry_id) is not None
    assert nav.get_entry(e4.entry_id) is not None


def test_navigate_to_non_user_message_points_directly_to_target() -> None:
    """Test time travel to assistant message sets leaf directly to target with no editor text."""
    nav = SessionTreeNavigator()

    e1 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Q1")
    e2 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="A1")
    _e3 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Q2")
    _e4 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="A2")

    res = nav.navigate_tree(e2.entry_id)
    assert res.new_leaf_id == e2.entry_id
    assert res.editor_text is None
    assert nav.get_leaf_id() == e2.entry_id

    branch = nav.get_branch()
    assert [b.entry_id for b in branch] == [e1.entry_id, e2.entry_id]

    # Navigation to same target is no-op
    noop_res = nav.navigate_tree(e2.entry_id)
    assert noop_res.is_noop is True


def test_navigate_with_branch_summary_computes_lca_and_attaches_summary_entry() -> None:
    """Test branch summary creation during navigation across branches."""
    nav = SessionTreeNavigator()

    # Root common base
    e1 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Root prompt")
    e2 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Root plan")

    # Branch A (which will be abandoned)
    _e3 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Explore branch A")
    _e4 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Branch A details")
    e5 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Branch A conclusion")

    # Navigate back to e2 with branch summary
    summary_msg = "Explored branch A, identified edge cases in auth token expiry."
    res = nav.navigate_tree(
        e2.entry_id,
        summarize=True,
        summary_text=summary_msg,
        label="AuthExploration",
        usage_tokens=850,
        cost_usd=0.012,
    )

    assert res.common_ancestor_id == e2.entry_id
    assert res.abandoned_entries_count == 3  # [e3, e4, e5]
    assert res.summary_entry is not None
    assert res.summary_entry.entry_type == SessionEntryType.BRANCH_SUMMARY
    assert res.summary_entry.content == summary_msg
    assert res.summary_entry.parent_id == e2.entry_id
    assert res.summary_entry.details["from_id"] == e5.entry_id
    assert res.summary_entry.details["common_ancestor_id"] == e2.entry_id
    assert res.summary_entry.details["abandoned_count"] == "3"
    assert res.summary_entry.details["label"] == "AuthExploration"

    # Current leaf is now the summary entry
    assert nav.get_leaf_id() == res.summary_entry.entry_id

    # New continuation starts from the summary node
    e6 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Now execute approach B")
    assert e6.parent_id == res.summary_entry.entry_id

    branch = nav.get_branch()
    assert [b.entry_id for b in branch] == [e1.entry_id, e2.entry_id, res.summary_entry.entry_id, e6.entry_id]


def test_tree_hierarchical_projection_get_tree() -> None:
    """Test get_tree hierarchical projection for graph/tree rendering."""
    nav = SessionTreeNavigator()

    # Build fork:
    #       e1
    #       |
    #       e2
    #      /  \
    #     e3   e5
    #     |
    #     e4
    e1 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Root")
    e2 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Fork root")
    e3 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Branch 1")
    e4 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="Branch 1 done")

    # Navigate to e2 and append Branch 2
    nav.navigate_tree(e2.entry_id)
    e5 = nav.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="Branch 2")

    tree = nav.get_tree()
    assert len(tree) == 1
    root = tree[0]
    assert isinstance(root, SessionTreeNode)
    assert root.entry.entry_id == e1.entry_id
    assert len(root.children) == 1

    node2 = root.children[0]
    assert node2.entry.entry_id == e2.entry_id
    assert len(node2.children) == 2  # e3 and e5 are siblings

    child_ids = {c.entry.entry_id for c in node2.children}
    assert child_ids == {e3.entry_id, e5.entry_id}

    node3 = next(c for c in node2.children if c.entry.entry_id == e3.entry_id)
    assert len(node3.children) == 1
    assert node3.children[0].entry.entry_id == e4.entry_id


def test_durable_disk_journal_recovery(tmp_path: Path) -> None:
    """Test full resurrection of branching session tree from append-only JSONL journal."""
    db_file = tmp_path / "session_tree.jsonl"

    # Step 1: Create session with branching and write to disk
    nav1 = SessionTreeNavigator(journal_path=db_file)
    m1 = nav1.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="M1")
    m2 = nav1.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="M2")
    m3 = nav1.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="M3")

    nav1.navigate_tree(m2.entry_id)
    m4 = nav1.append_entry(entry_type=SessionEntryType.MESSAGE, role="user", content="M4")

    assert db_file.exists()
    assert nav1.get_leaf_id() == m4.entry_id

    # Step 2: Simulate process reload from journal
    nav2 = SessionTreeNavigator(journal_path=db_file)
    assert nav2.get_leaf_id() == m4.entry_id
    assert nav2.get_entry(m1.entry_id) is not None
    assert nav2.get_entry(m2.entry_id) is not None
    assert nav2.get_entry(m3.entry_id) is not None
    assert nav2.get_entry(m4.entry_id) is not None

    # Check branch preservation on restored tree
    branch = nav2.get_branch()
    assert [b.entry_id for b in branch] == [m1.entry_id, m2.entry_id, m4.entry_id]

    # Step 3: Append new node on restored tree
    m5 = nav2.append_entry(entry_type=SessionEntryType.MESSAGE, role="assistant", content="M5")
    assert nav2.get_leaf_id() == m5.entry_id

    # Step 4: Third reload ensures appended records flushed to disk
    nav3 = SessionTreeNavigator(journal_path=db_file)
    assert nav3.get_leaf_id() == m5.entry_id
    assert [b.entry_id for b in nav3.get_branch()] == [m1.entry_id, m2.entry_id, m4.entry_id, m5.entry_id]
