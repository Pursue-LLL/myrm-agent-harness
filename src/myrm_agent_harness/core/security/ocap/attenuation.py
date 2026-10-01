"""One-way capability attenuation pipeline for child delegation.

[INPUT]
- .types::CapabilityHandle, ResourceScope, CapabilityAction, AttenuationError
- .token::sign_capability_handle

[OUTPUT]
- attenuate_capability: Derive narrower, short-lived child capability from parent
- validate_scope_subset: Pure mathematical check ensuring child scope is subset of parent

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


def _is_path_subscope(child_path: str, parent_pattern: str) -> bool:
    """Check if child_path is strictly within parent_pattern boundaries."""
    norm_child = os.path.normpath(child_path)
    norm_parent = os.path.normpath(parent_pattern)

    if norm_child == norm_parent:
        return True

    clean_parent = norm_parent.rstrip("/*")
    if norm_child.startswith(clean_parent + os.sep) or norm_child == clean_parent:
        return True

    return fnmatch.fnmatch(norm_child, norm_parent)


def _is_domain_subscope(child_domain: str, parent_domain: str) -> bool:
    """Check if child_domain is equal to or a subdomain of parent_domain."""
    c = child_domain.lower().strip()
    p = parent_domain.lower().strip()
    if c == p:
        return True
    if p.startswith("*."):
        suffix = p[2:]
        return c.endswith("." + suffix) or c == suffix
    return c.endswith("." + p)


def validate_scope_subset(child_scope: ResourceScope, parent_scope: ResourceScope) -> None:
    """Verify that child_scope is a strict subset of parent_scope."""
    if parent_scope.is_unrestricted():
        return

    if parent_scope.paths:
        if not child_scope.paths:
            raise AttenuationError("Child cannot have unrestricted paths when parent is restricted")
        for cp in child_scope.paths:
            if not any(_is_path_subscope(cp, pp) for pp in parent_scope.paths):
                raise AttenuationError(f"Path elevation denied: '{cp}' is outside parent path boundaries")

    if parent_scope.domains:
        if not child_scope.domains:
            raise AttenuationError("Child cannot have unrestricted domains when parent is restricted")
        for cd in child_scope.domains:
            if not any(_is_domain_subscope(cd, pd) for pd in parent_scope.domains):
                raise AttenuationError(f"Domain elevation denied: '{cd}' is outside parent domain whitelist")

    if parent_scope.mcp_tools:
        if not child_scope.mcp_tools:
            raise AttenuationError("Child cannot have unrestricted MCP access when parent is restricted")
        for cm in child_scope.mcp_tools:
            if not any(fnmatch.fnmatch(cm, pm) for pm in parent_scope.mcp_tools):
                raise AttenuationError(f"MCP elevation denied: '{cm}' is outside parent allowed tools")


def attenuate_capability(
    parent: CapabilityHandle,
    subject_id: str,
    target_scope: ResourceScope | None = None,
    target_actions: set[CapabilityAction] | frozenset[CapabilityAction] | None = None,
    ttl_seconds: float = 300.0,
    current_time: float | None = None,
) -> CapabilityHandle:
    """Derive an attenuated, unforgeable capability handle for a child agent.

    Args:
        parent: Valid parent capability handle
        subject_id: Identifier of the child recipient
        target_scope: Requested resource boundaries (defaults to parent scope)
        target_actions: Requested actions (must be subset of parent actions)
        ttl_seconds: Requested lifetime in seconds
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
