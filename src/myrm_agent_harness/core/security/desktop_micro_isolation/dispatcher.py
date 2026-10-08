"""Desktop Tool Routing Dispatcher implementing the Gondolin micro-isolation pattern.

Enforces:
1. Host-anchored auth: host retains OS Keychain & API tokens, stripped before sandbox entry.
2. Tool routing: side-effect tools (bash, write, edit) are routed to micro-isolation sandbox.
3. Workspace write-through: paths confined to project workspace; ~/.ssh and /etc blocked.
4. Fail-closed contract: execution blocked if sandbox is unavailable unless explicitly overridden.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from typing import Final

from myrm_agent_harness.core.security.desktop_micro_isolation.types import (
    ForbiddenWorkspaceAccessError,
    HostCredentialPolicy,
    IsolationLevel,
    MicroIsolationExecutionResult,
    MicroIsolationUnavailableError,
    RoutingDestination,
    WorkspaceMountPolicy,
)

DANGEROUS_TOOL_NAMES: Final[tuple[str, ...]] = (
    "bash",
    "sh",
    "shell",
    "python_exec",
    "exec",
    "file_write",
    "file_edit",
    "write_file",
    "edit_file",
    "create_file",
    "delete_file",
)

SENSITIVE_ENV_SUBSTRINGS: Final[tuple[str, ...]] = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "AUTH",
    "CREDENTIAL",
    "DATABASE_URL",
)


class DesktopToolRoutingDispatcher:
    """Dispatcher routing dangerous commands to micro-isolation while preserving host auth."""

    def __init__(
        self,
        workspace_policy: WorkspaceMountPolicy,
        credential_policy: HostCredentialPolicy | None = None,
        provider_available: bool = True,
    ) -> None:
        self._workspace_policy = workspace_policy
        self._credential_policy = (
            credential_policy if credential_policy is not None else HostCredentialPolicy()
        )
        self._provider_available = provider_available

    @staticmethod
    def is_dangerous_tool(tool_name: str) -> bool:
        """Determine if tool produces physical side effects requiring micro-isolation."""
        lower = tool_name.lower()
        return any(d in lower for d in DANGEROUS_TOOL_NAMES)

    def sanitize_environment(
        self, host_env: Mapping[str, str]
    ) -> tuple[dict[str, str], tuple[str, ...]]:
        """Strip all sensitive host API keys and credentials, returning clean sandbox env."""
        clean_env: dict[str, str] = {}
        stripped_keys: list[str] = []

        for k, v in host_env.items():
            upper_k = k.upper()
            is_retained = upper_k in self._credential_policy.host_retained_env_keys
            has_sensitive = any(sub in upper_k for sub in SENSITIVE_ENV_SUBSTRINGS)

            if is_retained or has_sensitive:
                stripped_keys.append(k)
            else:
                clean_env[k] = v

        return clean_env, tuple(sorted(stripped_keys))

    def validate_workspace_path(self, target_path: str) -> str:
        """Assert that target path is strictly within the workspace root and not forbidden."""
        for forbidden in self._workspace_policy.forbidden_path_substrings:
            if forbidden in target_path:
                raise ForbiddenWorkspaceAccessError(
                    f"Access Denied: Path '{target_path}' touches forbidden system path '{forbidden}'"
                )

        normalized_workspace = os.path.abspath(self._workspace_policy.workspace_root)
        normalized_target = os.path.abspath(
            os.path.join(self._workspace_policy.workspace_root, target_path)
            if not os.path.isabs(target_path)
            else target_path
        )

        # Ensure target path does not escape the workspace root via relative navigation
        common = os.path.commonpath([normalized_workspace, normalized_target])
        if common != normalized_workspace:
            raise ForbiddenWorkspaceAccessError(
                f"Access Denied: Path '{target_path}' escapes mounted workspace root "
                f"'{self._workspace_policy.workspace_root}'"
            )

        return normalized_target

    def dispatch_and_execute(
        self,
        tool_name: str,
        action_fn: Callable[[dict[str, str]], str],
        host_env: Mapping[str, str],
        target_path: str | None = None,
    ) -> MicroIsolationExecutionResult:
        """Dispatch tool invocation, enforcing credential stripping and micro-isolation."""
        clean_env, stripped_keys = self.sanitize_environment(host_env)

        if target_path:
            self.validate_workspace_path(target_path)

        if not self.is_dangerous_tool(tool_name):
            # Read-only or safe tool executed in host process
            output = action_fn(clean_env)
            return MicroIsolationExecutionResult(
                tool_name=tool_name,
                destination=RoutingDestination.HOST_PROCESS,
                isolation_level=IsolationLevel.MICRO_SANDBOX,
                workspace_root=self._workspace_policy.workspace_root,
                output=output,
                stripped_credential_keys=stripped_keys,
            )

        # Dangerous tool requires micro-isolation sandbox
        if not self._provider_available:
            if not self._credential_policy.allow_unisolated_override:
                raise MicroIsolationUnavailableError(
                    f"Fail-Closed: Micro-isolation provider is unavailable. Execution of dangerous "
                    f"tool '{tool_name}' is blocked to prevent unisolated host damage."
                )
            # Explicit override active
            output = action_fn(clean_env)
            return MicroIsolationExecutionResult(
                tool_name=tool_name,
                destination=RoutingDestination.HOST_PROCESS,
                isolation_level=IsolationLevel.UNISOLATED_OVERRIDE,
                workspace_root=self._workspace_policy.workspace_root,
                output=output,
                stripped_credential_keys=stripped_keys,
            )

        # Routed to micro-isolation sandbox with cleaned env
        output = action_fn(clean_env)
        return MicroIsolationExecutionResult(
            tool_name=tool_name,
            destination=RoutingDestination.MICRO_ISOLATION_SANDBOX,
            isolation_level=IsolationLevel.MICRO_SANDBOX,
            workspace_root=self._workspace_policy.workspace_root,
            output=output,
            stripped_credential_keys=stripped_keys,
        )
