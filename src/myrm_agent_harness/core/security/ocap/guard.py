"""Execution-layer enforcement guard for Object-Capability access.

[INPUT]
- .types::CapabilityAction, CapabilityHandle, CapabilityDeniedError, ResourceScope
- .context::get_current_capability
- .token::verify_capability_signature
- .attenuation::_is_path_subscope (POS: path boundary test, symlinked aliases and resolved paths are one boundary)

[OUTPUT]
- check_capability_access: Non-raising boolean access probe
- enforce_capability_access: Fail-closed assertion raising CapabilityDeniedError

[POS]
Physical gatekeeper invoked by the local file and shell executors.
Ensures operations fail-closed when capability handles are expired, unsigned, or out of scope.
A handle's validity is stateless: its signature and its expiry, nothing held per spawn.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.ocap.attenuation import _is_path_subscope
from myrm_agent_harness.core.security.ocap.context import get_current_capability
from myrm_agent_harness.core.security.ocap.token import verify_capability_signature
from myrm_agent_harness.core.security.ocap.types import (
    CapabilityAction,
    CapabilityDeniedError,
    CapabilityHandle,
    ResourceScope,
)


def _is_usable(handle: CapabilityHandle) -> bool:
    return not handle.is_expired() and verify_capability_signature(handle)


def _is_in_scope(scope: ResourceScope, target: str) -> bool:
    """A scope without path patterns constrains no path."""
    return not scope.paths or any(_is_path_subscope(target, pattern) for pattern in scope.paths)


def check_capability_access(
    action: CapabilityAction,
    target: str | None = None,
    handle: CapabilityHandle | None = None,
) -> bool:
    """Evaluate whether the given action on target is permitted by the active capability.

    Args:
        action: Requested capability action
        target: File path or working directory the action applies to
        handle: Explicit capability handle (falls back to active context)

    Returns:
        True if permitted; False if expired, unsigned, or out of scope.
    """
    active_handle = handle if handle is not None else get_current_capability()
    if active_handle is None:
        # No capability constraint active on current execution thread
        return True

    if not _is_usable(active_handle) or action not in active_handle.actions:
        return False

    return target is None or _is_in_scope(active_handle.scope, target)


def enforce_capability_access(
    action: CapabilityAction,
    target: str | None = None,
    handle: CapabilityHandle | None = None,
) -> None:
    """Enforce capability check, raising CapabilityDeniedError if unauthorized."""
    active_handle = handle if handle is not None else get_current_capability()
    if active_handle is None:
        return

    if not _is_usable(active_handle):
        raise CapabilityDeniedError(f"Capability handle '{active_handle.handle_id}' is invalid or expired.")

    if action not in active_handle.actions:
        raise CapabilityDeniedError(
            f"Action '{action.value}' denied by capability '{active_handle.handle_id}'. "
            f"Allowed actions: {[a.value for a in active_handle.actions]}"
        )

    if target is not None and not _is_in_scope(active_handle.scope, target):
        raise CapabilityDeniedError(
            f"Path '{target}' is outside granted capability boundaries: {list(active_handle.scope.paths)}"
        )
