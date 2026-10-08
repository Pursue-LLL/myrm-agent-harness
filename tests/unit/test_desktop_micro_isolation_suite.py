"""Unit tests for Desktop Host Auth & Tool Routing Micro-Isolation Suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.core.security.desktop_micro_isolation import (
    DesktopToolRoutingDispatcher,
    ForbiddenWorkspaceAccessError,
    HostCredentialPolicy,
    IsolationLevel,
    MicroIsolationUnavailableError,
    RoutingDestination,
    WorkspaceMountPolicy,
)


@pytest.fixture
def sample_workspace_policy(tmp_path: Path) -> WorkspaceMountPolicy:
    ws_dir = tmp_path / "sample_project"
    ws_dir.mkdir(parents=True, exist_ok=True)
    return WorkspaceMountPolicy(workspace_root=str(ws_dir))


def test_host_credential_stripping(sample_workspace_policy: WorkspaceMountPolicy) -> None:
    """Test sensitive host API keys are completely purged before entering sandbox."""
    dispatcher = DesktopToolRoutingDispatcher(workspace_policy=sample_workspace_policy)

    host_env = {
        "OPENAI_API_KEY": "sk-proj-super-secret-key-12345",
        "ANTHROPIC_API_KEY": "sk-ant-secret-key-67890",
        "DATABASE_URL": "postgres://admin:pwd@db:5432/main",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PROJECT_ENV": "development",
        "USER": "developer",
    }

    clean_env, stripped = dispatcher.sanitize_environment(host_env)

    # Assert credentials removed
    assert "OPENAI_API_KEY" not in clean_env
    assert "ANTHROPIC_API_KEY" not in clean_env
    assert "DATABASE_URL" not in clean_env
    assert set(stripped) == {"ANTHROPIC_API_KEY", "DATABASE_URL", "OPENAI_API_KEY"}

    # Assert safe variables preserved
    assert clean_env["PATH"] == "/usr/local/bin:/usr/bin:/bin"
    assert clean_env["PROJECT_ENV"] == "development"
    assert clean_env["USER"] == "developer"


def test_tool_routing_destination(sample_workspace_policy: WorkspaceMountPolicy) -> None:
    """Test safe read tools execute in host process while dangerous tools route to micro-sandbox."""
    dispatcher = DesktopToolRoutingDispatcher(workspace_policy=sample_workspace_policy)

    host_env = {"PATH": "/bin", "OPENAI_API_KEY": "sk-secret"}

    # 1. Safe tool -> HOST_PROCESS
    res_safe = dispatcher.dispatch_and_execute(
        tool_name="read_file",
        action_fn=lambda env: "read_success",
        host_env=host_env,
        target_path="README.md",
    )
    assert res_safe.destination == RoutingDestination.HOST_PROCESS
    assert res_safe.isolation_level == IsolationLevel.MICRO_SANDBOX
    assert res_safe.output == "read_success"

    # 2. Dangerous tool -> MICRO_ISOLATION_SANDBOX
    res_danger = dispatcher.dispatch_and_execute(
        tool_name="bash",
        action_fn=lambda env: "bash_executed",
        host_env=host_env,
    )
    assert res_danger.destination == RoutingDestination.MICRO_ISOLATION_SANDBOX
    assert res_danger.isolation_level == IsolationLevel.MICRO_SANDBOX
    assert res_danger.output == "bash_executed"


def test_workspace_boundary_protection(sample_workspace_policy: WorkspaceMountPolicy) -> None:
    """Test workspace confinement: forbidden paths and relative traversal escapes are blocked."""
    dispatcher = DesktopToolRoutingDispatcher(workspace_policy=sample_workspace_policy)

    # Valid internal path succeeds
    validated = dispatcher.validate_workspace_path("src/index.ts")
    assert validated.endswith("src/index.ts")

    # Forbidden system directory blocked (~/.ssh)
    with pytest.raises(ForbiddenWorkspaceAccessError, match="touches forbidden system path"):
        dispatcher.validate_workspace_path("/Users/developer/.ssh/id_rsa")

    # Traversal escaping workspace root blocked
    with pytest.raises(ForbiddenWorkspaceAccessError, match="escapes mounted workspace root"):
        dispatcher.validate_workspace_path("../outside_file.txt")


def test_fail_closed_contract(sample_workspace_policy: WorkspaceMountPolicy) -> None:
    """Test fail-closed contract: blocked when provider unavailable, unless explicit override."""
    # 1. Provider unavailable and no override -> fail-closed block
    dispatcher_fail_closed = DesktopToolRoutingDispatcher(
        workspace_policy=sample_workspace_policy,
        credential_policy=HostCredentialPolicy(allow_unisolated_override=False),
        provider_available=False,
    )

    with pytest.raises(MicroIsolationUnavailableError, match="Fail-Closed: Micro-isolation provider is unavailable"):
        dispatcher_fail_closed.dispatch_and_execute(
            tool_name="python_exec",
            action_fn=lambda env: "output",
            host_env={},
        )

    # 2. Explicit unisolated override allows execution with warning level
    dispatcher_override = DesktopToolRoutingDispatcher(
        workspace_policy=sample_workspace_policy,
        credential_policy=HostCredentialPolicy(allow_unisolated_override=True),
        provider_available=False,
    )

    res_override = dispatcher_override.dispatch_and_execute(
        tool_name="python_exec",
        action_fn=lambda env: "override_executed",
        host_env={},
    )
    assert res_override.destination == RoutingDestination.HOST_PROCESS
    assert res_override.isolation_level == IsolationLevel.UNISOLATED_OVERRIDE
    assert res_override.output == "override_executed"
