"""One-way capability attenuation pipeline for child delegation.

[INPUT]
- .types::CapabilityHandle, ResourceScope, CapabilityAction, AttenuationError
- .token::sign_capability_handle

[OUTPUT]
- attenuate_capability: Derive a narrower child capability from parent; the caller states the lifetime, which never exceeds the parent's expiry
- validate_scope_subset: Pure mathematical check ensuring child scope is subset of parent
- _is_path_subscope: Path boundary test shared with the guard (lexical match verified against realpath; symlinked aliases resolved by physical containment)

[POS]
Enforces the fundamental Object-Capability attenuation law:
Child capabilities can ONLY stay equal or narrow; ANY permission elevation is strictly blocked.
"""

from __future__ import annotations

import fnmatch
import os
import time
from uuid import uuid4

from myrm_agent_harness.core.security.ocap.token import sign_capability_handle
from myrm_agent_harness.core.security.ocap.types import (
    AttenuationError,
    CapabilityAction,
    CapabilityHandle,
    ResourceScope,
)


def _is_physically_contained(child_path: str, parent_dir: str) -> bool:
    """Check whether child_path resolves, through symlinks, inside the existing directory parent_dir.

    Only absolute paths qualify: resolving a relative one would depend on the process cwd.
    """
    if not (os.path.isabs(child_path) and os.path.isabs(parent_dir)):
        return False
    try:
        if not os.path.isdir(parent_dir):
            return False
        real_parent = os.path.realpath(parent_dir)
        real_child = os.path.realpath(child_path)
    except (OSError, ValueError):
        return False
    return real_child == real_parent or real_child.startswith(real_parent + os.sep)


def _is_path_subscope(child_path: str, parent_pattern: str) -> bool:
    """Check if child_path is strictly within parent_pattern boundaries.

    Containment is decided by physical location, so a root reached through a symlinked alias and
    its resolved form are the same boundary:
    1. A lexical normpath match must still resolve inside the pattern (blocks symlink traversal
       out of the boundary).
    2. Without a lexical match, the path is inside only if its symlink-resolved location lies
       within the pattern's existing directory (wildcard patterns never take this route).
    """
    norm_child = os.path.normpath(child_path)
    norm_parent = os.path.normpath(parent_pattern)

    clean_parent = norm_parent.rstrip("/*")

    lexical_match = (
        norm_child in (norm_parent, clean_parent)
        or norm_child.startswith(clean_parent + os.sep)
        or fnmatch.fnmatch(norm_child, norm_parent)
    )
    if not lexical_match:
        return _is_physically_contained(norm_child, clean_parent)

    try:
        if os.path.lexists(norm_child):
            real_child = os.path.realpath(norm_child)
            real_parent = os.path.realpath(clean_parent) if os.path.exists(clean_parent) else clean_parent
            if real_child != real_parent and not real_child.startswith(real_parent + os.sep):
                return False
    except (OSError, ValueError):
        return False

    return True


def validate_scope_subset(child_scope: ResourceScope, parent_scope: ResourceScope) -> None:
    """Verify that child_scope is a strict subset of parent_scope."""
    if parent_scope.is_unrestricted():
        return

    if child_scope.is_unrestricted():
        raise AttenuationError("Child cannot have unrestricted scope when parent is restricted")

    for cp in child_scope.paths:
        if not any(_is_path_subscope(cp, pp) for pp in parent_scope.paths):
            raise AttenuationError(f"Path elevation denied: '{cp}' is outside parent path boundaries")


def attenuate_capability(
    parent: CapabilityHandle,
    subject_id: str,
    *,
    ttl_seconds: float,
    target_scope: ResourceScope | None = None,
    target_actions: set[CapabilityAction] | frozenset[CapabilityAction] | None = None,
    current_time: float | None = None,
) -> CapabilityHandle:
    """Derive an attenuated, unforgeable capability handle for a child agent.

    Args:
        parent: Valid parent capability handle
        subject_id: Identifier of the child recipient
        ttl_seconds: Requested lifetime in seconds, always stated by the caller because it must cover
            the whole task the handle serves (the result is still clamped to the parent's expiry)
        target_scope: Requested resource boundaries (defaults to parent scope)
        target_actions: Requested actions (must be subset of parent actions)
        current_time: Optional monotonic clock anchor for testing

    Returns:
        Cryptographically signed attenuated CapabilityHandle

    Raises:
        AttenuationError: If requested scope or actions exceed parent boundaries
    """
    now = time.monotonic() if current_time is None else current_time
    if parent.is_expired(now):
        raise AttenuationError(f"Cannot attenuate from expired parent handle {parent.handle_id}")

    final_actions = frozenset(target_actions) if target_actions is not None else parent.actions
    unauthorized_actions = final_actions - parent.actions
    if unauthorized_actions:
        forbidden = ", ".join(sorted(a.value for a in unauthorized_actions))
        raise AttenuationError(f"Action elevation denied: requested unauthorized actions [{forbidden}]")

    final_scope = target_scope if target_scope is not None else parent.scope
    validate_scope_subset(final_scope, parent.scope)

    max_child_exp = parent.expires_at
    requested_exp = now + max(1.0, float(ttl_seconds))
    final_exp = min(requested_exp, max_child_exp)

    child_handle = CapabilityHandle(
        handle_id=f"cap-{uuid4().hex[:12]}",
        issuer_id=parent.subject_id,
        subject_id=subject_id,
        scope=final_scope,
        actions=final_actions,
        issued_at=now,
        expires_at=final_exp,
        parent_handle_id=parent.handle_id,
        signature="",
    )

    sig = sign_capability_handle(child_handle)
    return CapabilityHandle(
        handle_id=child_handle.handle_id,
        issuer_id=child_handle.issuer_id,
        subject_id=child_handle.subject_id,
        scope=child_handle.scope,
        actions=child_handle.actions,
        issued_at=child_handle.issued_at,
        expires_at=child_handle.expires_at,
        parent_handle_id=child_handle.parent_handle_id,
        signature=sig,
    )
