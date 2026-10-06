"""Tests for Hierarchical Project Context Matrix and Agent Dynamic Binding Gate."""

from myrm_agent_harness.runtime.context.hierarchical_project_matrix import (
    AgentDynamicBindingGate,
    GlobalAgentTier,
    HierarchicalContextMatrixComposer,
    ProjectWorkspaceTier,
    SessionGoalTier,
    WorkspaceHealthAndOrphanDetector,
    WorkspaceSessionRef,
)


def test_hierarchical_context_matrix_composition():
    agent_tier = GlobalAgentTier(
        agent_id="bot-arch-01",
        persona_name="Principal Systems Architect",
        system_prompt="You design distributed, low-latency agent engines.",
        private_skills=("kernel_profiling", "ipc_tracing"),
    )
    project_tier = ProjectWorkspaceTier(
        project_id="proj-myrm-core",
        project_name="Myrm Core Runtime",
        root_path="/workspace/myrm-core",
        project_instructions="Always use bun for package management. Follow PEP8 in python packages.",
        shared_artifacts_dir="/workspace/myrm-core/.artifacts",
        allowed_globs=("src/**", "tests/**", "docs/**"),
    )
    session_tier = SessionGoalTier(
        session_id="sess-task-99",
        session_intent="Refactor state capsule serialization engine",
        temporary_constraints=("Do not touch legacy v1 migrations", "Keep file lines < 400"),
        active_task_summary="Implementing atomic SHA-256 state bundling",
    )

    matrix = HierarchicalContextMatrixComposer.compose_matrix(
        agent_tier=agent_tier,
        project_tier=project_tier,
        session_tier=session_tier,
    )

    xml = matrix.rendered_prompt
    assert '<hierarchical_context_matrix version="1.0">' in xml
    assert '<tier_1_global_agent agent_id="bot-arch-01" persona="Principal Systems Architect">' in xml
    assert "kernel_profiling, ipc_tracing" in xml
    assert '<tier_2_project_workspace project_id="proj-myrm-core" name="Myrm Core Runtime" root="/workspace/myrm-core">' in xml
    assert "Always use bun for package management" in xml
    assert '<tier_3_session_goal session_id="sess-task-99" intent="Refactor state capsule serialization engine">' in xml
    assert "<constraint>Keep file lines &lt; 400</constraint>" in xml or "<constraint>Keep file lines < 400</constraint>" in xml
    assert "</hierarchical_context_matrix>" in xml


def test_agent_dynamic_binding_gate_lifecycle():
    gate = AgentDynamicBindingGate()

    # 1. Bind two agents to one project
    b1 = gate.bind_agent(
        agent_id="agent-coder",
        project_id="proj-alpha",
        role_description="Core Feature Developer",
        created_at_utc="2026-10-06T12:00:00Z",
    )
    b2 = gate.bind_agent(
        agent_id="agent-reviewer",
        project_id="proj-alpha",
        role_description="Security & Code Auditor",
        created_at_utc="2026-10-06T12:05:00Z",
    )

    assert b1.is_active
    assert b2.is_active
    assert gate.is_agent_bound("agent-coder", "proj-alpha")
    assert gate.is_agent_bound("agent-reviewer", "proj-alpha")
    assert not gate.is_agent_bound("agent-coder", "proj-beta")

    # 2. List bindings for project and agent
    proj_bindings = gate.list_bindings_for_project("proj-alpha")
    assert len(proj_bindings) == 2

    # Bind coder to second project
    gate.bind_agent(
        agent_id="agent-coder",
        project_id="proj-beta",
        role_description="DevOps Specialist",
        created_at_utc="2026-10-06T12:10:00Z",
    )
    coder_bindings = gate.list_bindings_for_agent("agent-coder")
    assert len(coder_bindings) == 2

    # 3. Unbind agent
    unbound = gate.unbind_agent("agent-reviewer", "proj-alpha")
    assert unbound
    assert not gate.is_agent_bound("agent-reviewer", "proj-alpha")
    assert len(gate.list_bindings_for_project("proj-alpha")) == 1


def test_workspace_health_and_orphan_detector():
    sessions = (
        WorkspaceSessionRef(
            session_id="sess-healthy-1",
            project_id="proj-alpha",
            artifact_count=3,
            last_active_at_utc="2026-10-06T12:00:00Z",
            is_archived=False,
        ),
        WorkspaceSessionRef(
            session_id="sess-orphan-1",
            project_id=None,  # Detached orphan
            artifact_count=0,
            last_active_at_utc="2026-09-01T12:00:00Z",
            is_archived=False,
        ),
        WorkspaceSessionRef(
            session_id="sess-foreign-1",
            project_id="proj-other",  # Belongs to another project
            artifact_count=0,
            last_active_at_utc="2026-09-01T12:00:00Z",
            is_archived=False,
        ),
        WorkspaceSessionRef(
            session_id="sess-stale-1",
            project_id="proj-alpha",
            artifact_count=0,
            last_active_at_utc="2026-08-01T12:00:00Z",
            is_archived=True,  # Archived with zero artifacts -> stale
        ),
    )

    gate = AgentDynamicBindingGate()
    gate.bind_agent(
        agent_id="agent-lead",
        project_id="proj-alpha",
        role_description="Lead",
        created_at_utc="2026-10-06T10:00:00Z",
    )
    bindings = gate.list_bindings_for_project("proj-alpha")

    report = WorkspaceHealthAndOrphanDetector.evaluate_workspace_health(
        project_id="proj-alpha",
        sessions=sessions,
        bindings=bindings,
    )

    assert report.total_sessions == 4
    assert "sess-orphan-1" in report.orphan_session_ids
    assert "sess-foreign-1" in report.orphan_session_ids
    assert "sess-stale-1" in report.stale_session_ids
    assert report.active_agents_count == 1
    assert "Workspace 'proj-alpha' has 4 sessions" in report.health_summary
