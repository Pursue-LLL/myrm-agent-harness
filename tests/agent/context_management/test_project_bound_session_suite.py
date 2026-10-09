"""Comprehensive tests for ProjectBoundSessionLauncherSuite.

[INPUT]
- project_bound_launcher package contracts and implementations.

[OUTPUT]
- Deterministic verification of workspace validation, git metadata inspection,
  context inheritance assembly, project-bound launching, parent branch inheritance,
  and master suite facade methods.

[POS]
- Sub-package: tests.agent.context_management
- Module: test_project_bound_session_suite.py
"""

import os
from pathlib import Path
import pytest
from myrm_agent_harness.agent.context_management.project_bound_launcher import (
    BoundSessionLaunchResult,
    ContextInheritanceAssembler,
    InheritedContextFrame,
    InheritanceStatus,
    LauncherSuiteConfig,
    ProjectBoundSessionLauncher,
    ProjectBoundSessionLauncherSuite,
    ProjectMetadataSnapshot,
    SessionLaunchMode,
    SessionLaunchRequest,
    WorkspaceMetadataInspector,
)


def test_workspace_metadata_inspector_validation(tmp_path: Path) -> None:
    """Verifies path syntax checks, directory traversal blocking, and sandbox fencing."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    valid_dir = sandbox / "repo_a"
    valid_dir.mkdir()

    inspector = WorkspaceMetadataInspector(sandbox_root=str(sandbox))

    # 1. Empty and whitespace paths rejected
    ok, err = inspector.validate_workspace_path("")
    assert ok is False
    assert "empty" in err

    # 2. Path traversal attack rejected
    ok_trav, err_trav = inspector.validate_workspace_path("../outside")
    assert ok_trav is False
    assert "traversal" in err_trav

    # 3. Valid directory inside sandbox accepted
    ok_valid, res_path = inspector.validate_workspace_path(str(valid_dir))
    assert ok_valid is True
    assert res_path == str(valid_dir.resolve())

    # 4. Out-of-sandbox path rejected when sandbox_root is set
    outside_dir = tmp_path / "escape"
    outside_dir.mkdir()
    ok_escape, err_escape = inspector.validate_workspace_path(str(outside_dir))
    assert ok_escape is False
    assert "outside sandbox" in err_escape


def test_workspace_metadata_inspector_git_discovery(tmp_path: Path) -> None:
    """Verifies lightweight git metadata detection via .git/HEAD file."""
    repo_dir = tmp_path / "mock_git_repo"
    repo_dir.mkdir()
    git_dir = repo_dir / ".git"
    git_dir.mkdir()
    head_file = git_dir / "HEAD"
    head_file.write_text("ref: refs/heads/feature/context-continuation\n", encoding="utf-8")

    sub_dir = repo_dir / "src" / "pkg"
    sub_dir.mkdir(parents=True)

    inspector = WorkspaceMetadataInspector()
    branch, repo_root = inspector.inspect_git_metadata(str(sub_dir))
    assert branch == "feature/context-continuation"
    assert repo_root == str(repo_dir.resolve())

    # Non-git directory falls back gracefully
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()
    b_none, r_none = inspector.inspect_git_metadata(str(non_git))
    assert b_none == ""
    assert r_none == ""


def test_context_inheritance_assembler() -> None:
    """Verifies synthesis of initial context prompt block with truncation safeguards."""
    assembler = ContextInheritanceAssembler()

    # 1. Quick chat without project binding
    frame_quick = assembler.assemble(
        project=None,
        effective_cwd="/tmp/quick",
        effective_agent_id="quick_agent",
        git_branch="main",
    )
    assert frame_quick.project_id is None
    assert frame_quick.inheritance_status == InheritanceStatus.NONE
    assert "[PROJECT_WORKSPACE_CONTEXT]" in frame_quick.context_prompt_block
    assert "Project Binding: None" in frame_quick.context_prompt_block
    assert "Working Directory: /tmp/quick" in frame_quick.context_prompt_block

    # 2. Bound project with rich goals and tags
    project = ProjectMetadataSnapshot(
        project_id="prj-alpha",
        name="Alpha High-Frequency Trading Core",
        workspace_path="/workspace/trading",
        default_agent_id="finance_quant_agent",
        goal_summary="Sub-millisecond order reconciliation and cryptographic ledger persistence.",
        description="Rust-based execution engine with Python harness integration.",
        git_branch="develop",
        tags=("fintech", "low-latency", "crypto"),
    )
    frame_bound = assembler.assemble(
        project=project,
        effective_cwd="/workspace/trading",
        effective_agent_id="finance_quant_agent",
        git_branch="develop",
    )
    assert frame_bound.project_id == "prj-alpha"
    assert frame_bound.inheritance_status == InheritanceStatus.INHERITED_FULL
    assert "Alpha High-Frequency Trading Core" in frame_bound.context_prompt_block
    assert "Sub-millisecond order reconciliation" in frame_bound.context_prompt_block
    assert "fintech, low-latency, crypto" in frame_bound.context_prompt_block

    # 3. Context truncation safeguard
    frame_truncated = assembler.assemble(
        project=project,
        effective_cwd="/workspace/trading",
        effective_agent_id="finance_quant_agent",
        git_branch="develop",
        max_chars=120,
    )
    assert frame_truncated.inheritance_status == InheritanceStatus.INHERITED_PARTIAL
    assert "... (truncated)" in frame_truncated.context_prompt_block
    assert frame_truncated.context_prompt_block.endswith("[/PROJECT_WORKSPACE_CONTEXT]")


def test_project_bound_session_launcher_modes() -> None:
    """Verifies launch modes: PROJECT_BOUND, BRANCHED_FROM_PARENT, and STANDALONE_QUICK_CHAT."""
    launcher = ProjectBoundSessionLauncher(
        LauncherSuiteConfig(
            allow_empty_project=False,
            fallback_workspace_path="/fallback/workspace",
            fallback_default_agent_id="base_agent",
        )
    )

    project_sample = ProjectMetadataSnapshot(
        project_id="prj-omega",
        name="Omega Distributed Compiler",
        workspace_path="/repos/omega",
        default_agent_id="compiler_architect",
        goal_summary="Multi-tenant WASM JIT orchestration engine.",
        git_branch="release-2.4",
    )
    launcher.register_project(project_sample)

    # 1. Project bound launch: succeeds and inherits workspace and agent
    req_bound = SessionLaunchRequest(
        target_session_id="session-001",
        project_id="prj-omega",
    )
    res_bound = launcher.launch_session(req_bound)
    assert res_bound.success is True
    assert res_bound.launch_mode == SessionLaunchMode.PROJECT_BOUND
    assert res_bound.inherited_frame.project_id == "prj-omega"
    assert res_bound.inherited_frame.agent_id == "compiler_architect"
    assert res_bound.inherited_frame.workspace_path == "/repos/omega"
    assert res_bound.inherited_frame.git_branch == "release-2.4"

    # 2. Overriding CWD and Agent ID in request takes precedence
    req_override = SessionLaunchRequest(
        target_session_id="session-002",
        project_id="prj-omega",
        custom_cwd="/custom/hotfix",
        custom_agent_id="hotfix_agent",
    )
    res_override = launcher.launch_session(req_override)
    assert res_override.inherited_frame.workspace_path == "/custom/hotfix"
    assert res_override.inherited_frame.agent_id == "hotfix_agent"

    # 3. Branched session from parent: inherits project and parent workspace
    req_branch = SessionLaunchRequest(
        target_session_id="session-003",
        parent_session_id="session-001",
        inherited_git_branch="feature/branch-exploration",
    )
    res_branch = launcher.launch_session(req_branch)
    assert res_branch.success is True
    assert res_branch.launch_mode == SessionLaunchMode.BRANCHED_FROM_PARENT
    assert res_branch.inherited_frame.project_id == "prj-omega"
    assert res_branch.inherited_frame.workspace_path == "/repos/omega"
    assert res_branch.inherited_frame.git_branch == "feature/branch-exploration"

    # 4. Standalone quick chat
    req_quick = SessionLaunchRequest(
        target_session_id="session-004",
        project_id=None,
    )
    res_quick = launcher.launch_session(req_quick)
    assert res_quick.success is True
    assert res_quick.launch_mode == SessionLaunchMode.STANDALONE_QUICK_CHAT
    assert res_quick.inherited_frame.project_id is None
    assert res_quick.inherited_frame.agent_id == "base_agent"

    # 5. Invalid project rejected when allow_empty_project is False
    req_invalid = SessionLaunchRequest(
        target_session_id="session-005",
        project_id="prj-non-existent",
    )
    res_invalid = launcher.launch_session(req_invalid)
    assert res_invalid.success is False
    assert "not found" in res_invalid.message


def test_project_bound_session_suite_facade() -> None:
    """Verifies end-to-end orchestration through ProjectBoundSessionLauncherSuite facade."""
    suite = ProjectBoundSessionLauncherSuite()

    project = ProjectMetadataSnapshot(
        project_id="prj-suite",
        name="Suite Integration Testbed",
        workspace_path="/workspace/testbed",
        default_agent_id="test_suite_agent",
        goal_summary="End-to-end integration testing.",
    )
    suite.register_project(project)
    assert len(suite.list_projects()) == 1
    assert suite.get_project("prj-suite") is not None

    # 1. Launch project session
    res_proj = suite.launch_project_session(
        session_id="s-proj-1",
        project_id="prj-suite",
        initial_prompt="Run baseline audit.",
    )
    assert res_proj.success is True
    assert res_proj.inherited_frame.project_id == "prj-suite"
    assert "Suite Integration Testbed" in res_proj.inherited_frame.context_prompt_block

    # 2. Launch branched session
    res_branch = suite.launch_branch_session(
        session_id="s-branch-1",
        parent_session_id="s-proj-1",
        inherited_git_branch="branch-qa",
    )
    assert res_branch.success is True
    assert res_branch.inherited_frame.project_id == "prj-suite"
    assert res_branch.inherited_frame.git_branch == "branch-qa"

    # 3. Launch quick chat
    res_quick = suite.launch_quick_chat(session_id="s-quick-1")
    assert res_quick.success is True
    assert res_quick.inherited_frame.project_id is None

    # 4. Retrieve stored frame
    frame = suite.get_session_frame("s-proj-1")
    assert frame is not None
    assert frame.project_id == "prj-suite"
