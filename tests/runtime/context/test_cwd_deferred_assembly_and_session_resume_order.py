"""Unit test suite for CwdDeferredWorkspaceServiceBindingAndSessionResumeOrder (Item 107).

Verifies strict outside-in assembly stages:
1. ENTRY_PARSE -> 2. SESSION_RESOLVED -> 3. CWD_RESOLVED -> 4. SERVICES_BOUND -> 5. RUNTIME_READY.
Ensures workspace services are never prematurely bound, eliminating directory drift and out-of-bounds watchers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.cwd_deferred_assembly_guard import (
    CwdDeferredAssemblyGuard,
)
from myrm_agent_harness.runtime.context.cwd_deferred_assembly_types import (
    AssemblyOrderViolationError,
    AssemblyStageKind,
    SessionMetadataHeader,
)
from myrm_agent_harness.runtime.context.deferred_session_runtime_factory import (
    DeferredSessionRuntimeFactory,
    MockWorkspaceService,
)


def test_guard_strict_outside_in_order_enforcement(tmp_path: Path) -> None:
    """Verify that jumping stages or binding services prematurely raises AssemblyOrderViolationError."""
    guard = CwdDeferredAssemblyGuard()
    assert guard.current_stage == AssemblyStageKind.ENTRY_PARSE

    # Attempting to resolve CWD before session metadata resolution must fail
    with pytest.raises(AssemblyOrderViolationError) as exc_info:
        guard.resolve_and_relocate_cwd(str(tmp_path))
    assert "cannot perform 'resolve_cwd'" in str(exc_info.value)

    # Attempting to bind service in ENTRY_PARSE must fail
    with pytest.raises(AssemblyOrderViolationError) as exc_info_srv:
        guard.register_service_binding("git_service")
    assert "cannot be constructed before CWD resolution" in str(exc_info_srv.value)

    # Valid step 1 -> step 2
    guard.advance_stage(AssemblyStageKind.SESSION_RESOLVED)
    assert guard.current_stage == AssemblyStageKind.SESSION_RESOLVED

    # Valid step 2 -> step 3
    resolved = guard.resolve_and_relocate_cwd(str(tmp_path))
    assert resolved == str(tmp_path.resolve())
    assert guard.current_stage == AssemblyStageKind.CWD_RESOLVED

    # Valid step 3 -> step 4
    desc = guard.register_service_binding("git_service")
    assert desc.bound_cwd == str(tmp_path.resolve())
    assert guard.current_stage == AssemblyStageKind.SERVICES_BOUND

    # Valid step 4 -> step 5
    audit = guard.complete_runtime_assembly()
    assert guard.current_stage == AssemblyStageKind.RUNTIME_READY
    assert len(audit) >= 5


def test_guard_backward_transition_prevention() -> None:
    """Verify that backwards stage transition is forbidden."""
    guard = CwdDeferredAssemblyGuard()
    guard.advance_stage(AssemblyStageKind.SESSION_RESOLVED)

    with pytest.raises(AssemblyOrderViolationError) as exc_info:
        guard.advance_stage(AssemblyStageKind.ENTRY_PARSE)
    assert "Cannot transition backwards" in str(exc_info.value)


def test_deferred_factory_binds_historical_session_cwd(tmp_path: Path) -> None:
    """Verify factory defers service construction until session CWD is authoritative."""
    project_a = tmp_path / "project_a"
    project_b = tmp_path / "project_b"
    project_a.mkdir()
    project_b.mkdir()

    factory = DeferredSessionRuntimeFactory()

    # Historical session was recorded in project_b
    header = SessionMetadataHeader(
        session_id="session-historical-99",
        original_cwd=str(project_b),
        workspace_name="RepoB",
    )

    created_service_cwds: dict[str, str] = {}

    def _make_git_service(bound_cwd: str) -> MockWorkspaceService:
        created_service_cwds["git"] = bound_cwd
        return MockWorkspaceService(bound_cwd=bound_cwd, service_name="git")

    def _make_linter_service(bound_cwd: str) -> MockWorkspaceService:
        created_service_cwds["linter"] = bound_cwd
        return MockWorkspaceService(bound_cwd=bound_cwd, service_name="linter")

    container, verification = factory.assemble_session_runtime(
        header,
        service_factories={
            "git": _make_git_service,
            "linter": _make_linter_service,
        },
    )

    assert verification.valid is True
    assert verification.resolved_cwd == str(project_b.resolve())
    assert verification.is_relocated is False

    # Check that services were strictly bound to project_b, NOT project_a or system root
    assert created_service_cwds["git"] == str(project_b.resolve())
    assert created_service_cwds["linter"] == str(project_b.resolve())
    assert container.calibrated_cwd == str(project_b.resolve())
    assert "git" in container.services
    assert "linter" in container.services


def test_deferred_factory_dynamic_relocation_on_missing_dir(tmp_path: Path) -> None:
    """Verify factory gracefully relocates missing directories when fallback is provided."""
    non_existent_cwd = tmp_path / "machine_x" / "deleted_workspace"
    fallback_dir = tmp_path / "safe_fallback"
    fallback_dir.mkdir()

    factory = DeferredSessionRuntimeFactory(default_fallback_cwd=str(fallback_dir))

    header = SessionMetadataHeader(
        session_id="session-relocated-01",
        original_cwd=str(non_existent_cwd),
    )

    container, verification = factory.assemble_session_runtime(
        header,
        service_factories={
            "search": lambda cwd: MockWorkspaceService(bound_cwd=cwd, service_name="search"),
        },
    )

    assert verification.valid is True
    assert verification.is_relocated is True
    assert verification.resolved_cwd == str(fallback_dir.resolve())
    assert container.calibrated_cwd == str(fallback_dir.resolve())
    assert any("dynamically relocated" in log for log in verification.assembly_order_log)


def test_deferred_factory_fails_closed_when_missing_and_no_fallback(tmp_path: Path) -> None:
    """Verify factory strictly fails closed if CWD is missing and no fallback exists."""
    missing_cwd = tmp_path / "nowhere"
    factory = DeferredSessionRuntimeFactory(default_fallback_cwd=None)

    header = SessionMetadataHeader(
        session_id="session-fail-closed",
        original_cwd=str(missing_cwd),
    )

    with pytest.raises(ValueError) as exc_info:
        factory.assemble_session_runtime(
            header,
            service_factories={
                "git": lambda cwd: MockWorkspaceService(bound_cwd=cwd, service_name="git"),
            },
        )
    assert "missing or forbidden, and no fallback provided" in str(exc_info.value)
