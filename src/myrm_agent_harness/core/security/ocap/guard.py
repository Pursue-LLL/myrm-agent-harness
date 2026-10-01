"""Execution-layer enforcement guard for Object-Capability access.

[INPUT]
- .types::CapabilityAction, CapabilityHandle, CapabilityDeniedError
- .context::get_current_capability
- .registry::get_default_capability_registry, CapabilityRegistry
- .attenuation::_is_path_subscope, _is_domain_subscope

[OUTPUT]
- check_capability_access: Non-raising boolean access probe
- enforce_capability_access: Fail-closed assertion raising CapabilityDeniedError

[POS]
Physical gatekeeper invoked by tool executors (file_ops, bash, web_fetch, MCP).
Ensures operations fail-closed when capability handles are missing, expired, revoked, or out of scope.
"""

from __future__ import annotations

import fnmatch
from typing import TYPE_CHECKING

from myrm_agent_harness.core.security.ocap.attenuation import _is_domain_subscope, _is_path_subscope
from myrm_agent_harness.core.security.ocap.context import get_current_capability
from myrm_agent_harness.core.security.ocap.registry import (
    CapabilityRegistry,
    get_default_capability_registry,
)
from myrm_agent_harness.core.security.ocap.types import (
    CapabilityAction,
    CapabilityDeniedError,
    CapabilityHandle,
)

if TYPE_CHECKING:
    pass


def check_capability_access(
    action: CapabilityAction,
    target: str | None = None,
    handle: CapabilityHandle | None = None,
    registry: CapabilityRegistry | None = None,
) -> bool:
    """Evaluate whether the given action on target is permitted by the active capability.

    Args:
        action: Requested capability action
        target: Resource target (file path, egress domain, or MCP tool name)
        handle: Explicit capability handle (falls back to active context)
        registry: CapabilityRegistry to verify validity (falls back to default)

    Returns:
        True if permitted; False if revoked, expired, or out of scope.
    """
    active_handle = handle if handle is not None else get_current_capability()
    if active_handle is None:
        # No capability constraint active on current execution thread
        return True

    active_registry = registry if registry is not None else get_default_capability_registry()
    if not active_registry.is_valid(active_handle):
        return False

    if action not in active_handle.actions:
        return False

    if target is None:
        return True

    scope = active_handle.scope
    if action in (CapabilityAction.READ, CapabilityAction.WRITE, CapabilityAction.EXECUTE):
        if scope.paths:
            return any(_is_path_subscope(target, p) for p in scope.paths)

    elif action == CapabilityAction.EGRESS:
        if scope.domains:
            return any(_is_domain_subscope(target, d) for d in scope.domains)

    elif action == CapabilityAction.MCP:
        if scope.mcp_tools:
            return any(fnmatch.fnmatch(target, m) for m in scope.mcp_tools)

    return True


def enforce_capability_access(
    action: CapabilityAction,
    target: str | None = None,
    handle: CapabilityHandle | None = None,
    registry: CapabilityRegistry | None = None,
) -> None:
    """Enforce capability check, raising CapabilityDeniedError if unauthorized."""
    active_handle = handle if handle is not None else get_current_capability()
    if active_handle is None:
        return

    active_registry = registry if registry is not None else get_default_capability_registry()
    if not active_registry.is_valid(active_handle):
        raise CapabilityDeniedError(
            f"Capability handle '{active_handle.handle_id}' is invalid, expired, or revoked."
        )

    if action not in active_handle.actions:
        raise CapabilityDeniedError(
            f"Action '{action.value}' denied by capability '{active_handle.handle_id}'. "
            f"Allowed actions: {[a.value for a in active_handle.actions]}"
        )

    if target is not None:
        scope = active_handle.scope
        if action in (CapabilityAction.READ, CapabilityAction.WRITE, CapabilityAction.EXECUTE):
            if scope.paths and not any(_is_path_subscope(target, p) for p in scope.paths):
                raise CapabilityDeniedError(
                    f"Path '{target}' is outside granted capability boundaries: {list(scope.paths)}"
                )
        elif action == CapabilityAction.EGRESS:
            if scope.domains and not any(_is_domain_subscope(target, d) for d in scope.domains):
                raise CapabilityDeniedError(
                    f"Egress domain '{target}' is not in capability whitelist: {list(scope.domains)}"
                )
        elif action == CapabilityAction.MCP:
            if scope.mcp_tools and not any(fnmatch.fnmatch(target, m) for m in scope.mcp_tools):
                raise CapabilityDeniedError(
                    f"MCP tool '{target}' is not in capability whitelist: {list(scope.mcp_tools)}"
                )
