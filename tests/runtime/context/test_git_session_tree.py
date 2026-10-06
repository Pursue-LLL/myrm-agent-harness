"""Unit tests for Git-like non-linear session tree and branching engine."""

from __future__ import annotations

import json

import pytest

from myrm_agent_harness.runtime.context.git_session_tree import (
    GitLikeSessionTreeEngine,
)
from myrm_agent_harness.runtime.context.git_session_tree_types import (
    SessionTreeEntryKind,
)


def test_git_session_tree_append_and_linear_context() -> None:
    """Verifies sequential node append and bottom-up linear context assembly."""
    engine = GitLikeSessionTreeEngine()

    n1 = engine.append_entry("Hello, I am user.", role="user")
    assert engine.root_node_id == n1.node_id
    assert engine.active_head_id == n1.node_id
    assert n1.parent_id is None

    n2 = engine.append_entry("Hi, how can I help you?", role="assistant")
    assert n2.parent_id == n1.node_id
    assert engine.active_head_id == n2.node_id

    n3 = engine.append_entry("Write a Python script.", role="user")
    assert n3.parent_id == n2.node_id

    # Build linear context from active head
    chain = engine.build_linear_context()
    assert len(chain) == 3
    assert [n.node_id for n in chain] == [n1.node_id, n2.node_id, n3.node_id]
    assert chain[0].content == "Hello, I am user."
    assert chain[2].content == "Write a Python script."


def test_git_session_tree_branch_and_isolation() -> None:
    """Verifies forking a new branch from any historical node with context isolation."""
    engine = GitLikeSessionTreeEngine()

    n1 = engine.append_entry("Initial setup", role="system")
    n2 = engine.append_entry("Task: design database schema", role="user")
    n3_main = engine.append_entry("Option A: use PostgreSQL", role="assistant")

    # Fork branch 'sqlite-branch' from n2
    engine.branch(source_node_id=n2.node_id, branch_name="sqlite-branch")
    assert engine.active_branch_name == "sqlite-branch"
    assert engine.active_head_id == n2.node_id

    # Append on sqlite branch
    n3_sqlite = engine.append_entry("Option B: use SQLite with WAL mode", role="assistant")
    assert n3_sqlite.parent_id == n2.node_id

    # Verify context on sqlite branch: [n1, n2, n3_sqlite]
    chain_sqlite = engine.build_linear_context()
    assert [n.node_id for n in chain_sqlite] == [n1.node_id, n2.node_id, n3_sqlite.node_id]

    # Verify main branch context: [n1, n2, n3_main]
    chain_main = engine.build_linear_context(from_node_id=n3_main.node_id)
    assert [n.node_id for n in chain_main] == [n1.node_id, n2.node_id, n3_main.node_id]

    # Verify topology
    topo = engine.export_topology()
    assert topo.total_nodes == 4
    assert topo.total_branches == 2
    assert "main" in topo.branch_heads
    assert "sqlite-branch" in topo.branch_heads


def test_git_session_tree_checkout() -> None:
    """Verifies switching active cursor across branches and nodes."""
    engine = GitLikeSessionTreeEngine()

    n1 = engine.append_entry("Root node")
    n2_main = engine.append_entry("Main line work")

    engine.branch(source_node_id=n1.node_id, branch_name="experiment")
    n2_exp = engine.append_entry("Experimental work")

    # Switch back to main branch
    node_switched = engine.checkout("main")
    assert node_switched.node_id == n2_main.node_id
    assert engine.active_branch_name == "main"
    assert engine.active_head_id == n2_main.node_id

    # Switch to experiment branch
    node_exp = engine.checkout("experiment")
    assert node_exp.node_id == n2_exp.node_id
    assert engine.active_branch_name == "experiment"

    # Checkout directly by node_id
    node_root = engine.checkout(n1.node_id)
    assert node_root.node_id == n1.node_id

    with pytest.raises(ValueError, match="neither a known branch"):
        engine.checkout("non-existent-branch")


def test_git_session_tree_rewind_lossless() -> None:
    """Verifies rewinding N turns along parent chain while losslessly retaining future child nodes."""
    engine = GitLikeSessionTreeEngine()

    n1 = engine.append_entry("Step 1")
    n2 = engine.append_entry("Step 2")
    engine.append_entry("Step 3")
    n4 = engine.append_entry("Step 4")

    # Rewind 2 steps (should land on Step 2)
    rewound_node = engine.rewind(steps=2)
    assert rewound_node.node_id == n2.node_id
    assert engine.active_head_id == n2.node_id

    # Linear context from active head now ends at Step 2
    context = engine.build_linear_context()
    assert [n.node_id for n in context] == [n1.node_id, n2.node_id]

    # Future child nodes (n3, n4) are STILL intact in the tree and can be checked out
    checked_out = engine.checkout(n4.node_id)
    assert checked_out.node_id == n4.node_id
    full_context = engine.build_linear_context()
    assert len(full_context) == 4


def test_git_session_tree_compaction_and_jsonl_serialization() -> None:
    """Verifies compaction boundary truncation and JSONL export serialization."""
    engine = GitLikeSessionTreeEngine()

    engine.append_entry("Turn 1 - old detail")
    engine.append_entry("Turn 2 - another detail")
    compaction_node = engine.append_entry(
        "Summary: User prefers async Python with SQLite WAL.",
        role="system",
        entry_kind=SessionTreeEntryKind.COMPACTION_CHECKPOINT,
    )
    engine.append_entry("Turn 3 - new query based on summary")

    # Without stop_at_compaction: all 4 nodes
    full_context = engine.build_linear_context(stop_at_compaction=False)
    assert len(full_context) == 4

    # With stop_at_compaction: only compaction checkpoint + subsequent nodes
    compact_context = engine.build_linear_context(stop_at_compaction=True)
    assert len(compact_context) == 2
    assert compact_context[0].node_id == compaction_node.node_id
    assert compact_context[0].entry_kind == SessionTreeEntryKind.COMPACTION_CHECKPOINT

    # JSONL Export verification
    jsonl_output = engine.export_jsonl()
    lines = [json.loads(line) for line in jsonl_output.strip().splitlines()]
    assert len(lines) == 4
    assert lines[2]["entry_kind"] == "compaction_checkpoint"
