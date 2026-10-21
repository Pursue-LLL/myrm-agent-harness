"""Unit tests for Agent Session Multiplexer and cross-agent inspect/instruct mechanisms.

[INPUT]
- myrm_agent_harness.agent.sub_agents.multiplexer::(
    AgentSessionMultiplexer,
    create_inspect_agent_session_tool,
    create_instruct_agent_tool,
  )

[OUTPUT]
- Pytest test cases validating session multiplexing, sliding log inspection, instruction injection, and tools.

[POS]
tests/agent/sub_agents/test_agent_multiplexer.py: Comprehensive test suite for Item 7 AgentMultiplexer.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.multiplexer import (
    AgentSessionMultiplexer,
    create_inspect_agent_session_tool,
    create_instruct_agent_tool,
)


def test_session_registration_and_listing() -> None:
    """Verify session registration, state management, and filtered listing."""
    mux = AgentSessionMultiplexer()

    s1 = mux.register_session(
        session_id="sess-worker-1",
        agent_type="coder",
        task_objective="Implement auth service",
        parent_session_id="sess-parent-root",
        is_headless=False,
    )
    s2 = mux.register_session(
        session_id="sess-worker-2",
        agent_type="researcher",
        task_objective="Crawl security advisories",
        parent_session_id="sess-parent-root",
        is_headless=True,
    )

    assert s1.session_id == "sess-worker-1"
    assert s1.state == "running"
    assert s2.is_headless is True

    # List all for parent
    parent_sessions = mux.list_sessions(parent_session_id="sess-parent-root")
    assert len(parent_sessions) == 2

    # Filter by headless
    headless_sessions = mux.list_sessions(is_headless=True)
    assert len(headless_sessions) == 1
    assert headless_sessions[0].session_id == "sess-worker-2"

    # State update
    mux.update_session_state("sess-worker-1", "completed")
    completed = mux.list_sessions(state="completed")
    assert len(completed) == 1
    assert completed[0].session_id == "sess-worker-1"


def test_log_sliding_buffer_and_artifacts() -> None:
    """Verify circular log buffer maintains sliding window and records artifacts."""
    mux = AgentSessionMultiplexer(max_log_lines=5)

    mux.register_session(
        session_id="sess-logger",
        agent_type="coder",
        task_objective="Test logging",
    )

    # Append 8 log lines, only the last 5 should be retained
    for i in range(1, 9):
        mux.append_log("sess-logger", f"Log line {i}")

    mux.record_artifact("sess-logger", "/workspace/output.json")
    mux.record_artifact("sess-logger", "/workspace/report.md")

    snapshot = mux.inspect_session("sess-logger", tail_lines=10)
    assert snapshot is not None
    assert len(snapshot.log_tail) == 5
    assert snapshot.log_tail[0] == "Log line 4"
    assert snapshot.log_tail[-1] == "Log line 8"
    assert snapshot.artifacts == ["/workspace/output.json", "/workspace/report.md"]


def test_cross_agent_inspect_snapshot() -> None:
    """Verify inspect snapshot returns complete observational data."""
    mux = AgentSessionMultiplexer()
    mux.register_session(
        session_id="sess-inspectee",
        agent_type="architect",
        task_objective="Design distributed event mesh",
    )
    mux.append_log("sess-inspectee", "Analyzing latency boundaries...")
    mux.append_log("sess-inspectee", "Synthesizing consensus requirements...")

    snapshot = mux.inspect_session("sess-inspectee", tail_lines=2)
    assert snapshot is not None
    assert snapshot.agent_type == "architect"
    assert snapshot.state == "running"
    assert len(snapshot.log_tail) == 2
    assert "Analyzing latency boundaries..." in snapshot.log_tail[0]

    # Non-existent session
    assert mux.inspect_session("sess-not-found") is None


def test_cross_agent_instruction_injection_and_consumption() -> None:
    """Verify one agent injecting instructions into another and consumption lifecycle."""
    mux = AgentSessionMultiplexer()
    mux.register_session(
        session_id="sess-target",
        agent_type="coder",
        task_objective="Build database migration",
    )

    # Inject first instruction
    r1 = mux.inject_instruction(
        "sess-target",
        "Please use asyncpg connection pool rather than blocking psycopg2.",
        source_agent="architect",
    )
    assert r1.success is True
    assert r1.queued_instructions_count == 1

    # Inject second instruction
    r2 = mux.inject_instruction(
        "sess-target",
        "Remember to add rollback handling in case DDL fails.",
        source_agent="security-auditor",
    )
    assert r2.success is True
    assert r2.queued_instructions_count == 2

    # Verify inspect reflects pending instruction count
    snap = mux.inspect_session("sess-target")
    assert snap is not None
    assert snap.pending_instructions_count == 2

    # Target agent consumes instructions
    consumed = mux.consume_pending_instructions("sess-target")
    assert len(consumed) == 2
    assert consumed[0].source_agent == "architect"
    assert "asyncpg" in consumed[0].instruction
    assert consumed[1].source_agent == "security-auditor"

    # Now pending count is zero
    snap_after = mux.inspect_session("sess-target")
    assert snap_after is not None
    assert snap_after.pending_instructions_count == 0


def test_inspect_agent_session_tool() -> None:
    """Verify LangChain inspect_agent_session tool execution."""
    mux = AgentSessionMultiplexer()
    mux.register_session(
        session_id="sess-sub-42",
        agent_type="db-admin",
        task_objective="Migrate schema",
    )
    mux.append_log("sess-sub-42", "Running alembic upgrade head...")

    tool = create_inspect_agent_session_tool(multiplexer=mux)
    result = tool.invoke({"target_session_id": "sess-sub-42", "tail_lines": 10})

    assert isinstance(result, dict)
    assert result["success"] is True
    assert result["agent_type"] == "db-admin"
    assert result["log_tail"] == ["Running alembic upgrade head..."]

    # Invocation on missing session returns error payload
    err_res = tool.invoke({"target_session_id": "sess-missing"})
    assert isinstance(err_res, dict)
    assert err_res["success"] is False
    assert "not found" in str(err_res.get("error", ""))


def test_instruct_agent_tool() -> None:
    """Verify LangChain instruct_agent tool execution."""
    mux = AgentSessionMultiplexer()
    mux.register_session(
        session_id="sess-sub-99",
        agent_type="coder",
        task_objective="Implement OAuth callback",
    )

    tool = create_instruct_agent_tool(multiplexer=mux, current_agent_type="lead-orchestrator")
    result = tool.invoke({
        "target_session_id": "sess-sub-99",
        "instruction": "Verify CSRF state parameter before exchanging auth code.",
    })

    assert isinstance(result, dict)
    assert result["success"] is True
    assert result["queued_instructions_count"] == 1

    # Verify instruction was recorded with proper source
    instructions = mux.consume_pending_instructions("sess-sub-99")
    assert len(instructions) == 1
    assert instructions[0].source_agent == "lead-orchestrator"
    assert "CSRF" in instructions[0].instruction
