# ============================================================================
# Unit Tests: Standardized Agent Handoff Brief & Continuity Bridge (Item 170)
# ============================================================================

import pytest

from myrm_agent_harness.agent.context_management.handoff_brief import (
    DecisionItem,
    DelegationRoleKind,
    StandardizedAgentHandoffBridge,
)


def test_create_brief_and_render_handoff_xml() -> None:
    """Test creating structured handoff brief and rendering dense XML context."""
    bridge = StandardizedAgentHandoffBridge()
    source_session = "session-chat-yesterday"

    decisions = [
        DecisionItem(
            what="Use Pytest and Pydantic v2 strict models",
            why="Enforce runtime type contracts without Any types",
            category="architecture",
        ),
        DecisionItem(
            what="Avoid external Redis dependency, use SQLite WAL",
            why="Local-first offline sandbox requirement",
            category="architecture",
        ),
    ]

    brief = bridge.create_brief(
        source_session_id=source_session,
        task_goal="Refactor agent context pipeline to support prefix caching",
        completed_steps=["Design RFC 8785 canonicalizer", "Implement append-only guard"],
        blocked_points=["Waiting for frontend bridge approval"],
        decisions=decisions,
        relevant_files=["src/pipeline.py", "tests/test_pipeline.py"],
        env_dependencies={"MYRM_SANDBOX_MODE": "local", "PYTHONUNBUFFERED": "1"},
    )

    assert brief.source_session_id == source_session
    assert len(brief.decisions) == 2
    assert len(brief.completed_steps) == 2
    assert len(brief.relevant_files) == 2

    xml = bridge.render_handoff_xml(brief)
    assert '<agent_handoff_brief source_session="session-chat-yesterday"' in xml
    assert "<task_goal>Refactor agent context pipeline" in xml
    assert '<decision what="Use Pytest and Pydantic v2 strict models"' in xml
    assert 'why="Enforce runtime type contracts without Any types"' in xml
    assert "<item>Design RFC 8785 canonicalizer</item>" in xml
    assert "<item>Waiting for frontend bridge approval</item>" in xml
    assert '<env key="MYRM_SANDBOX_MODE" value="local" />' in xml


def test_import_to_session_state_continuity() -> None:
    """Test importing brief into new session for instant state continuity."""
    bridge = StandardizedAgentHandoffBridge()

    brief = bridge.create_brief(
        source_session_id="session-day-1",
        task_goal="Build e-commerce checkout flow",
        completed_steps=["Cart item calculation"],
        decisions=[DecisionItem(what="Do not use Stripe SDK directly", why="PCI-DSS enclave requirement")],
        relevant_files=["checkout/cart.py"],
    )

    # Next day: User opens brand new session-day-2 and clicks "Accept Handoff"
    ingress_res = bridge.import_to_session(
        target_session_id="session-day-2",
        brief=brief,
    )

    assert ingress_res.target_session_id == "session-day-2"
    assert ingress_res.source_session_id == "session-day-1"
    assert ingress_res.brief_id == brief.brief_id
    assert ingress_res.injected_token_estimate > 0
    assert "PCI-DSS enclave requirement" in ingress_res.injected_xml_context

    # Verify queryable active handoff
    active = bridge.get_session_active_handoff("session-day-2")
    assert active is not None
    assert active.brief_id == brief.brief_id


def test_role_scoped_brief_delegation() -> None:
    """Test delegating scoped brief tailored for specific subagent profile."""
    bridge = StandardizedAgentHandoffBridge()

    brief = bridge.create_brief(
        source_session_id="session-lead-agent",
        task_goal="Fullstack application refactor",
        decisions=[
            DecisionItem(what="OAuth PKCE only", why="Security hardening", category="security"),
            DecisionItem(what="Tailwind CSS v4", why="Modern frontend styling", category="frontend"),
            DecisionItem(what="Docker multi-stage build", why="Image size optimization", category="infra"),
        ],
        relevant_files=[
            "src/auth.py",
            "frontend/App.tsx",
            "docker/Dockerfile",
        ],
        env_dependencies={"PORT": "8080"},
    )

    # 1. Scope for Code Auditor
    auditor_brief = bridge.create_role_scoped_brief(brief, DelegationRoleKind.CODE_AUDITOR)
    assert len(auditor_brief.decisions) == 1
    assert auditor_brief.decisions[0].what == "OAuth PKCE only"
    assert auditor_brief.relevant_files == ("src/auth.py",)

    # 2. Scope for Frontend Specialist
    fe_brief = bridge.create_role_scoped_brief(brief, DelegationRoleKind.FRONTEND_SPECIALIST)
    assert len(fe_brief.decisions) == 1
    assert fe_brief.decisions[0].what == "Tailwind CSS v4"
    assert fe_brief.relevant_files == ("frontend/App.tsx",)

    # 3. Scope for General Agent (no filtering)
    gen_brief = bridge.create_role_scoped_brief(brief, DelegationRoleKind.GENERAL_AGENT)
    assert len(gen_brief.decisions) == 3


def test_brief_persistence_and_query_boundaries() -> None:
    """Test retrieval boundaries for existing and non-existing briefs and sessions."""
    bridge = StandardizedAgentHandoffBridge()

    assert bridge.get_brief("non-existent-brief") is None
    assert bridge.get_session_active_handoff("non-existent-session") is None

    brief = bridge.create_brief(source_session_id="sess-persist", task_goal="Task 1")
    retrieved = bridge.get_brief(brief.brief_id)
    assert retrieved is not None
    assert retrieved.task_goal == "Task 1"
