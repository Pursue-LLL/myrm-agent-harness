"""Unit tests for ProjectHierarchySessionArchiveAndKeywordResurrection.

Validates the Project-Task-Session tree hierarchy, multi-field full-text search,
cross-task relevance ranking, and seamless agent breakpoint resurrection.
"""

from __future__ import annotations

import time

from myrm_agent_harness.runtime.context.project_hierarchy_session_index import (
    ProjectHierarchySessionIndex,
)
from myrm_agent_harness.runtime.context.project_hierarchy_session_types import (
    ArchivedMessageEntry,
    ArchivedSessionNode,
    HierarchyHitKind,
    ProjectNode,
    ResurrectionStatus,
    TaskNode,
)
from myrm_agent_harness.runtime.context.session_keyword_resurrection_engine import (
    SessionKeywordResurrectionEngine,
)


def test_project_hierarchy_session_index_and_search() -> None:
    index = ProjectHierarchySessionIndex()

    # 1. Register projects
    p1 = ProjectNode(
        project_id="proj_auth",
        name="Authentication Service",
        description="OAuth2 and JWT token authentication infrastructure",
        workspace_path="/workspace/auth",
        tags=("security", "backend"),
    )
    p2 = ProjectNode(
        project_id="proj_billing",
        name="Billing Engine",
        description="Stripe subscription recurring billing and invoices",
        workspace_path="/workspace/billing",
        tags=("finance", "stripe"),
    )
    index.register_project(p1)
    index.register_project(p2)

    # 2. Register tasks
    t1 = TaskNode(
        task_id="task_jwt_expiry",
        project_id="proj_auth",
        title="Fix JWT Clock Skew Bug",
        description="Tokens rejected due to microsecond clock skew across distributed pods",
        status="resolved",
    )
    t2 = TaskNode(
        task_id="task_stripe_webhook",
        project_id="proj_billing",
        title="Handle Idempotent Webhook Retries",
        description="Prevent double-charging on network timeout re-deliveries",
        status="open",
    )
    index.register_task(t1)
    index.register_task(t2)

    # 3. Archive sessions
    now = time.time()
    s1 = ArchivedSessionNode(
        session_id="sess_jwt_debug",
        task_id="task_jwt_expiry",
        project_id="proj_auth",
        title="Investigate Token Expired At Validation",
        description="Root caused clock drift in PyJWT verification",
        agent_model="gpt-5-pro",
        status="completed",
        created_at=now - 3600,
        last_active=now - 1800,
        total_messages=4,
        total_tokens=4200,
        checkpoint_summary="Identified leeway=10 param missing in decode_token",
    )
    m1 = ArchivedMessageEntry(
        message_id="msg_001",
        session_id="sess_jwt_debug",
        role="user",
        content="Our mobile clients get 401 Unauthorized right after login",
    )
    m2 = ArchivedMessageEntry(
        message_id="msg_002",
        session_id="sess_jwt_debug",
        role="assistant",
        content="Inspecting pyjwt decode method. Found ExpiredSignatureError due to 50ms clock drift.",
        error_traces=("ExpiredSignatureError: Signature has expired",),
        file_references=("auth/jwt_validator.py",),
    )
    index.archive_session(s1, [m1, m2])

    # 4. Search by error trace keyword
    res_error = index.search("ExpiredSignatureError")
    assert res_error.total_hits >= 1
    assert len(res_error.groups) >= 1
    assert res_error.groups[0].project.project_id == "proj_auth"

    msg_hit = next(h for h in res_error.groups[0].matches if h.kind == HierarchyHitKind.MESSAGE)
    assert "ExpiredSignatureError" in msg_hit.snippet
    assert "error_traces" in msg_hit.matched_fields

    # 5. Search by file reference
    res_file = index.search("jwt_validator.py")
    assert res_file.total_hits >= 1
    assert any("file_references" in h.matched_fields for h in res_file.groups[0].matches)

    # 6. Search with project scope filter
    res_scoped = index.search("token", project_id="proj_auth")
    assert res_scoped.total_hits >= 1
    assert all(g.project.project_id == "proj_auth" for g in res_scoped.groups)

    res_empty_scope = index.search("token", project_id="proj_billing")
    assert res_empty_scope.total_hits == 0


def test_session_keyword_resurrection_engine() -> None:
    index = ProjectHierarchySessionIndex()
    engine = SessionKeywordResurrectionEngine(index=index)

    p = ProjectNode(
        project_id="proj_infra",
        name="Infrastructure Terraform",
        description="AWS ECS cluster and VPC deployment",
        workspace_path="/workspace/infra",
    )
    t = TaskNode(
        task_id="task_ecs_deploy",
        project_id="proj_infra",
        title="Upgrade ECS Fargate Cluster",
        description="Migrate task definitions to platform version 1.4.0",
    )
    s = ArchivedSessionNode(
        session_id="sess_ecs_001",
        task_id="task_ecs_deploy",
        project_id="proj_infra",
        title="Fargate Migration Step 1",
        description="Dry run terraform plan and state lock inspection",
        agent_model="claude-3-7-sonnet",
        checkpoint_summary="Terraform plan succeeded; 3 resources to update",
        total_tokens=6500,
    )
    m = ArchivedMessageEntry(
        message_id="msg_m1",
        session_id="sess_ecs_001",
        role="assistant",
        content="Terraform plan output saved. Pending approval for terraform apply.",
    )
    index.register_project(p)
    index.register_task(t)
    index.archive_session(s, [m])

    # Test direct resurrection
    bundle = engine.resurrect_session(
        "sess_ecs_001",
        continuation_instruction="Proceed to run terraform apply with auto-approve.",
    )
    assert bundle.status == ResurrectionStatus.READY
    assert bundle.session_id == "sess_ecs_001"
    assert bundle.project.name == "Infrastructure Terraform"
    assert bundle.task.title == "Upgrade ECS Fargate Cluster"
    assert len(bundle.messages) == 1
    assert bundle.restored_tokens == 6500
    assert "Historical Agent Resurrection" in bundle.resurrection_prompt
    assert "Proceed to run terraform apply" in bundle.resurrection_prompt

    # Test search and resurrect best
    searched_bundle = engine.search_and_resurrect_best(
        "Fargate",
        continuation_instruction="Check container health checks.",
    )
    assert searched_bundle is not None
    assert searched_bundle.session_id == "sess_ecs_001"
    assert "Check container health checks" in searched_bundle.resurrection_prompt


def test_session_resurrection_fallback_handling() -> None:
    engine = SessionKeywordResurrectionEngine()

    # Resurrecting non-existent session
    bundle = engine.resurrect_session("non_existent_session_id")
    assert bundle.status == ResurrectionStatus.FAILED
    assert bundle.messages == ()
    assert bundle.restored_tokens == 0

    # Search and resurrect non-matching query
    searched = engine.search_and_resurrect_best("completely_unknown_keyword_xyz")
    assert searched is None
