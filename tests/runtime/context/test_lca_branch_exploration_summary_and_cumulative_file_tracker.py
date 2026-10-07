"""Tests for LCA branch exploration summary and cumulative file tracker engine (Item 105).

Verifies lowest common ancestor calculation, abandoned exploration synthesis,
and cumulative mathematical union file tracking across multi-turn branches.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.cumulative_file_tracker import (
    CumulativeFileTracker,
)
from myrm_agent_harness.runtime.context.lca_branch_exploration_summary_engine import (
    LCABranchExplorationSummaryEngine,
    collect_abandoned_path,
    find_lowest_common_ancestor,
)
from myrm_agent_harness.runtime.context.lca_branch_summary_types import (
    CumulativeFileFootprint,
)
from myrm_agent_harness.runtime.context.session_tree_navigator import (
    SessionEntryType,
    SessionTreeNodeEntry,
)


def _make_entry(
    entry_id: str,
    parent_id: str | None,
    content: str = "",
    role: str = "assistant",
    details: dict[str, str] | None = None,
) -> SessionTreeNodeEntry:
    return SessionTreeNodeEntry(
        entry_id=entry_id,
        parent_id=parent_id,
        entry_type=SessionEntryType.MESSAGE,
        role=role,
        content=content,
        timestamp_ms=1700000000000,
        details=details or {},
    )


def test_lowest_common_ancestor_and_abandoned_path() -> None:
    """Test LCA resolution and abandoned path collection across forked branch topology."""
    # Topology:
    # root -> n1 -> n2a -> n3a (Branch A)
    #            \-> n2b -> n3b (Branch B)
    nodes: dict[str, SessionTreeNodeEntry] = {
        "root": _make_entry("root", None, content="Initial setup", role="system"),
        "n1": _make_entry("n1", "root", content="User task prompt", role="user"),
        "n2a": _make_entry("n2a", "n1", content="Exploration attempt on branch A"),
        "n3a": _make_entry("n3a", "n2a", content="Failed experiment on branch A"),
        "n2b": _make_entry("n2b", "n1", content="New approach on branch B"),
        "n3b": _make_entry("n3b", "n2b", content="Successful step on branch B"),
    }

    # LCA of n3a and n3b must be n1
    lca_id = find_lowest_common_ancestor("n3a", "n3b", nodes)
    assert lca_id == "n1"

    # Abandoned path from n3a up to n1 should be [n2a, n3a]
    abandoned = collect_abandoned_path("n3a", lca_id, nodes)
    assert len(abandoned) == 2
    assert [e.entry_id for e in abandoned] == ["n2a", "n3a"]

    # Same node LCA test
    assert find_lowest_common_ancestor("n3a", "n3a", nodes) == "n3a"

    # Lineage ancestor LCA test
    assert find_lowest_common_ancestor("n3a", "n1", nodes) == "n1"


def test_cumulative_file_tracker_tool_extractions_and_union() -> None:
    """Verify CumulativeFileTracker extracts operations and preserves exact mathematical union."""
    tracker = CumulativeFileTracker()

    # Turn 1: tool call for view_file
    reads1, mods1 = tracker.extract_from_tool_call("view_file", {"AbsolutePath": "/app/src/main.py"})
    assert reads1 == ("/app/src/main.py",)
    assert mods1 == ()
    tracker.record_operations(read_files=reads1, modified_files=mods1)

    # Turn 2: tool call for replace_file_content (as JSON string)
    reads2, mods2 = tracker.extract_from_tool_call(
        "replace_file_content",
        '{"TargetFile": "/app/src/main.py", "Instruction": "fix bug"}',
    )
    assert reads2 == ()
    assert mods2 == ("/app/src/main.py",)
    tracker.record_operations(read_files=reads2, modified_files=mods2)

    # Turn 3: tool call for write_to_file
    reads3, mods3 = tracker.extract_from_tool_call(
        "write_to_file",
        {"TargetFile": "/app/tests/test_main.py", "CodeContent": "def test(): pass"},
    )
    tracker.record_operations(read_files=reads3, modified_files=mods3)

    footprint = tracker.footprint
    assert footprint.read_files == ("/app/src/main.py",)
    assert footprint.modified_files == ("/app/src/main.py", "/app/tests/test_main.py")

    # Verify XML and markdown rendering
    xml = footprint.render_xml_block()
    assert "<cumulative-read-files>" in xml
    assert "<file>/app/src/main.py</file>" in xml
    assert "<cumulative-modified-files>" in xml
    assert "<file>/app/tests/test_main.py</file>" in xml

    md = footprint.render_markdown_block()
    assert "Cumulative Read Files (1)" in md
    assert "Cumulative Modified Files (2)" in md


def test_cumulative_file_tracker_from_entries_and_xml_blocks() -> None:
    """Verify accumulation from session entries with details and XML blocks."""
    tracker = CumulativeFileTracker()

    entry1 = _make_entry(
        "e1",
        None,
        content="Read config file",
        details={"tool_name": "read_file", "path": "/etc/config.json"},
    )
    entry2 = _make_entry(
        "e2",
        "e1",
        content="Prior summary\n<read-files>\n  <file>/docs/spec.md</file>\n</read-files>",
    )
    entry3 = _make_entry(
        "e3",
        "e2",
        content="Editing doc",
        details={"tool_name": "edit_file", "path": "/docs/spec.md"},
    )

    tracker.accumulate_from_entries([entry1, entry2, entry3])
    fp = tracker.footprint

    assert sorted(fp.read_files) == ["/docs/spec.md", "/etc/config.json"]
    assert sorted(fp.modified_files) == ["/docs/spec.md"]

    # Test incremental diff calculation against baseline
    baseline = CumulativeFileFootprint(read_files=("/docs/spec.md",))
    diff_reads, diff_mods = tracker.compute_incremental_diff(baseline)
    assert diff_reads == ("/etc/config.json",)
    assert diff_mods == ("/docs/spec.md",)


def test_lca_branch_exploration_summary_handoff_engine() -> None:
    """Verify LCABranchExplorationSummaryEngine creates rich insights from discarded branches."""
    engine = LCABranchExplorationSummaryEngine()

    nodes: dict[str, SessionTreeNodeEntry] = {
        "root": _make_entry("root", None, content="Repo initialized", role="system"),
        "task_prompt": _make_entry("task_prompt", "root", content="Refactor cache service", role="user"),
        # Abandoned Branch A
        "a1": _make_entry(
            "a1",
            "task_prompt",
            content="Attempt Redis cluster backend",
            role="assistant",
            details={"tool_name": "view_file", "path": "/src/redis_client.py"},
        ),
        "a2": _make_entry(
            "a2",
            "a1",
            content="Error: connection refused to redis cluster\nTraceback in cluster init",
            role="assistant",
            details={"tool_name": "replace_file_content", "path": "/src/redis_client.py"},
        ),
        # Target Branch B fork point (forks from task_prompt)
        "b1": _make_entry("b1", "task_prompt", content="Switch to in-memory SQLite cache instead", role="user"),
    }

    # Execute handoff from leaf a2 to new leaf b1
    handoff = engine.execute_branch_handoff(
        source_leaf_id="a2",
        target_node_id="b1",
        nodes_by_id=nodes,
        custom_lessons=["Do not assume local Redis cluster daemon is running"],
    )

    assert not handoff.is_noop
    assert handoff.lca_node_id == "task_prompt"
    assert handoff.abandoned_entries_count == 2
    assert handoff.summary is not None

    summary = handoff.summary
    assert "/src/redis_client.py" in summary.cumulative_files.read_files
    assert "/src/redis_client.py" in summary.cumulative_files.modified_files
    assert any("Error: connection refused" in lesson for lesson in summary.pitfalls_and_lessons)
    assert any("Do not assume local Redis cluster" in lesson for lesson in summary.pitfalls_and_lessons)

    # Verify context block projection
    context_block = LCABranchExplorationSummaryEngine.project_summary_to_context_block(summary)
    assert "[PRIOR_BRANCH_EXPLORATION_EXPERIENCE]" in context_block
    assert "redis_client.py" in context_block
    assert "[END_PRIOR_BRANCH_EXPERIENCE]" in context_block


def test_multi_branch_hopping_and_compaction_union_preservation() -> None:
    """Verify 0 amnesia across multi-hop branch switching and repeated unions."""
    engine = LCABranchExplorationSummaryEngine()

    # Hop 1: Branch 1 explored f1.py and f2.py
    fp1 = CumulativeFileFootprint(
        read_files=("/src/f1.py", "/src/f2.py"),
        modified_files=("/src/f1.py",),
    )
    engine.file_tracker.merge_footprint(fp1)

    # Hop 2: Branch 2 explored f2.py and f3.py
    fp2 = CumulativeFileFootprint(
        read_files=("/src/f2.py", "/src/f3.py"),
        modified_files=("/src/f3.py",),
    )
    engine.file_tracker.merge_footprint(fp2)

    # Hop 3: Compaction cycle added f4.py
    fp3 = CumulativeFileFootprint(
        read_files=("/src/f4.py",),
        modified_files=("/src/f4.py",),
    )
    engine.file_tracker.merge_footprint(fp3)

    final_fp = engine.file_tracker.footprint
    assert final_fp.read_files == ("/src/f1.py", "/src/f2.py", "/src/f3.py", "/src/f4.py")
    assert final_fp.modified_files == ("/src/f1.py", "/src/f3.py", "/src/f4.py")
