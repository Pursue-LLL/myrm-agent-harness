"""Tests for Dual-Track Session Entry & Operation Branch Projection Suite (Item 236)."""

from myrm_agent_harness.agent.context_management.branch_projection import (
    BranchSummary,
    DualTrackBranchProjectionEngine,
    EntryKind,
    OperationStatus,
    ProjectedContext,
    SessionEntry,
    SessionOperation,
    TokenUsage,
    collect_departed_entries,
    find_lca,
    synthesize_branch_delta_summary,
)


def test_dual_track_entry_and_telemetry_isolation() -> None:
    """Verify that domain facts (Entry) and runtime telemetry (Operation) are cleanly decoupled."""
    engine = DualTrackBranchProjectionEngine()
    session_id = "sess-dual-01"
    root_branch_id = engine.create_session(session_id=session_id, root_branch_name="main")

    # 1. Record domain facts
    entry1 = engine.record_entry(
        session_id=session_id,
        branch_id=root_branch_id,
        kind=EntryKind.MESSAGE,
        payload={"role": "user", "content": "Analyze PostgreSQL connection pooling latency."},
    )
    entry2 = engine.record_entry(
        session_id=session_id,
        branch_id=root_branch_id,
        kind=EntryKind.MODEL_CHANGE,
        payload={"model": "claude-3-7-sonnet"},
    )
    entry3 = engine.record_entry(
        session_id=session_id,
        branch_id=root_branch_id,
        kind=EntryKind.THINKING_LEVEL,
        payload={"thinking_level": "medium"},
    )
    entry4 = engine.record_entry(
        session_id=session_id,
        branch_id=root_branch_id,
        kind=EntryKind.ACTIVE_TOOLS,
        payload={"tools": "bash,read_file,write_file"},
    )

    # 2. Record runtime operational telemetry (out-of-band)
    op1 = SessionOperation(
        operation_id="op-101",
        session_id=session_id,
        branch_id=root_branch_id,
        step_name="tool_call_bash",
        started_at_ms=1000,
        ended_at_ms=1250,
        duration_ms=250,
        retry_count=0,
        token_usage=TokenUsage(input_tokens=1500, output_tokens=320, cached_tokens=1000),
        status=OperationStatus.SUCCESS,
        entry_id=entry1.entry_id,
        tool_name="bash",
        queue_wait_ms=12,
    )
    engine.record_operation(op1)

    # 3. Query telemetry and assert isolation
    ops = engine.get_operations(session_id=session_id, branch_id=root_branch_id)
    assert len(ops) == 1
    assert ops[0].operation_id == "op-101"
    assert ops[0].token_usage.total_tokens == 1820
    assert ops[0].duration_ms == 250

    # 4. Project context and verify operational telemetry incurs 0 token / message tax
    proj = engine.build_context_projection(branch_id=root_branch_id)
    assert proj.session_id == session_id
    assert proj.effective_model == "claude-3-7-sonnet"
    assert proj.effective_thinking_level == "medium"
    assert proj.effective_active_tools == ("bash", "read_file", "write_file")
    # Only the user message is projected into LLM messages; config entries update state; op1 is excluded!
    assert len(proj.projected_messages) == 1
    assert proj.projected_messages[0]["content"] == "Analyze PostgreSQL connection pooling latency."


def test_zero_copy_forking_and_divergence() -> None:
    """Verify zero-copy branch forking sharing antecedent history without data cloning."""
    engine = DualTrackBranchProjectionEngine()
    session_id = "sess-fork-02"
    main_branch = engine.create_session(session_id=session_id, root_branch_name="main")

    # Seed shared ancestor turn
    e_root = engine.record_entry(
        session_id=session_id,
        branch_id=main_branch,
        kind=EntryKind.MESSAGE,
        payload={"role": "user", "content": "Refactor database migration script."},
    )

    # Fork new experimental branch at e_root (O(1) complexity)
    exp_branch = engine.fork_branch(
        source_branch_id=main_branch,
        new_branch_name="experiment-alembic",
        at_entry_id=e_root.entry_id,
    )

    # Advance main branch
    e_main_1 = engine.record_entry(
        session_id=session_id,
        branch_id=main_branch,
        kind=EntryKind.MESSAGE,
        payload={"role": "assistant", "content": "Approach A: Use raw SQL scripts."},
    )

    # Advance experiment branch independently
    e_exp_1 = engine.record_entry(
        session_id=session_id,
        branch_id=exp_branch,
        kind=EntryKind.MESSAGE,
        payload={"role": "assistant", "content": "Approach B: Adopt Alembic autogenerate."},
    )

    # Project context for main branch
    proj_main = engine.build_context_projection(branch_id=main_branch)
    main_contents = [m["content"] for m in proj_main.projected_messages]
    assert "Refactor database migration script." in main_contents
    assert "Approach A: Use raw SQL scripts." in main_contents
    assert "Approach B: Adopt Alembic autogenerate." not in main_contents

    # Project context for experimental branch
    proj_exp = engine.build_context_projection(branch_id=exp_branch)
    exp_contents = [m["content"] for m in proj_exp.projected_messages]
    assert "Refactor database migration script." in exp_contents
    assert "Approach B: Adopt Alembic autogenerate." in exp_contents
    assert "Approach A: Use raw SQL scripts." not in exp_contents

    # Verify branch topology
    topology = engine.get_branch_topology(session_id)
    assert main_branch in topology
    assert exp_branch in topology
    assert topology[exp_branch] == "experiment-alembic"


def test_lca_discovery_and_delta_summary_synthesis() -> None:
    """Verify lowest common ancestor computation and lossless delta exploration summary."""
    engine = DualTrackBranchProjectionEngine()
    session_id = "sess-lca-03"
    main_branch = engine.create_session(session_id=session_id, root_branch_name="main")

    # Common root
    e_root = engine.record_entry(
        session_id=session_id,
        branch_id=main_branch,
        kind=EntryKind.MESSAGE,
        payload={"role": "user", "content": "Optimize search indexing pipeline."},
    )

    # Fork feature branch
    feat_branch = engine.fork_branch(
        source_branch_id=main_branch,
        new_branch_name="feature-tantivy",
        at_entry_id=e_root.entry_id,
    )

    # In feature branch: read files, make a decision, encounter a blocker
    engine.record_entry(
        session_id=session_id,
        branch_id=feat_branch,
        kind=EntryKind.MESSAGE,
        payload={
            "role": "assistant",
            "content": "Decision: Switch to Tantivy Rust engine for inverted index.",
            "tool_name": "read_file",
        },
        metadata={"read_files": "src/indexer/pipeline.rs,Cargo.toml"},
    )
    engine.record_entry(
        session_id=session_id,
        branch_id=feat_branch,
        kind=EntryKind.MESSAGE,
        payload={
            "role": "assistant",
            "content": "Compilation error: mismatched types in Tantivy schema builder.",
            "error_message": "Type mismatch at schema.rs:42",
        },
        metadata={"modified_files": "src/indexer/schema.rs"},
    )

    # Switch back from feat_branch to main_branch
    summary = engine.switch_branch(
        from_branch_id=feat_branch,
        to_branch_id=main_branch,
        inject_summary_to_target=True,
    )

    assert summary is not None
    assert summary.lca_entry_id == e_root.entry_id
    assert summary.source_branch_id == feat_branch
    assert summary.target_branch_id == main_branch
    assert "src/indexer/pipeline.rs" in summary.read_files
    assert "Cargo.toml" in summary.read_files
    assert "src/indexer/schema.rs" in summary.modified_files
    assert any("Decision:" in d for d in summary.key_decisions)
    assert any("Type mismatch" in b for b in summary.blockers)

    # Project main branch working set: should now cleanly inherit the summary without raw failed dialog
    proj_main = engine.build_context_projection(branch_id=main_branch)
    assert len(proj_main.projected_messages) == 2
    # First message: initial prompt
    assert proj_main.projected_messages[0]["content"] == "Optimize search indexing pipeline."
    # Second message: injected branch summary!
    summary_msg = proj_main.projected_messages[1]
    assert summary_msg["role"] == "system"
    assert "[Cross-Branch Exploration Context]" in summary_msg["content"]
    assert "Tantivy" in summary_msg["content"]
    assert "Cargo.toml" in summary_msg["content"]


def test_compaction_and_model_change_projection_sequence() -> None:
    """Verify compaction entries and multiple model changes project correctly."""
    engine = DualTrackBranchProjectionEngine()
    session_id = "sess-compact-04"
    branch_id = engine.create_session(session_id=session_id, root_branch_name="main")

    engine.record_entry(
        session_id=session_id,
        branch_id=branch_id,
        kind=EntryKind.MESSAGE,
        payload={"role": "user", "content": "Initial kickoff query."},
    )
    engine.record_entry(
        session_id=session_id,
        branch_id=branch_id,
        kind=EntryKind.COMPACTION,
        payload={"summary": "Previous turns resolved environment prerequisites."},
    )
    engine.record_entry(
        session_id=session_id,
        branch_id=branch_id,
        kind=EntryKind.MODEL_CHANGE,
        payload={"model": "gpt-4o"},
    )
    engine.record_entry(
        session_id=session_id,
        branch_id=branch_id,
        kind=EntryKind.MESSAGE,
        payload={"role": "assistant", "content": "Ready to execute with gpt-4o."},
    )

    proj = engine.build_context_projection(branch_id=branch_id)
    assert proj.effective_model == "gpt-4o"
    assert len(proj.projected_messages) == 3
    assert proj.projected_messages[0]["content"] == "Initial kickoff query."
    assert "[Context Compacted]" in proj.projected_messages[1]["content"]
    assert proj.projected_messages[2]["content"] == "Ready to execute with gpt-4o."
