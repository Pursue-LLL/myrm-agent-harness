"""Capability handle minted for each delegated subagent.

[INPUT]
- agent.security.checks::check_path_policy (POS: path zones shared with the approval engine)
- agent.security.session_access::merge_path_policy_with_session_access (POS: directories the user authorized for this session)
- core.security.ocap::CapabilityHandle, ResourceScope, attenuate_capability, check_capability_access, get_current_capability, sign_capability_handle (POS: signed per-spawn capability enforced by the file and shell executors)
- core.security.types::PathPolicy, PermissionAction, SecurityConfig

[OUTPUT]
- parent_capability_handle: the handle the running (delegating) agent is bound to, if any
- authorized_context_paths: model-supplied paths the parent may itself reach without further approval
- derive_spawn_capability: mint the child's handle from the parent's workspace, authorized directories and own handle
- derive_verifier_capability: mint a verifier's handle, the delegating agent's reach without WRITE

[POS]
The only producer of subagent capability handles. A handle's authority comes from the parent's real
workspace and the user's authorized directories, never from model-supplied tool arguments. The caller
binds the handle with ``capability_scope``; that binding is the only channel, so the handle a spawn is
attenuated from is the very one the executors enforce.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from uuid import uuid4

from myrm_agent_harness.core.security.ocap import (
    CapabilityAction,
    CapabilityHandle,
    ResourceScope,
    attenuate_capability,
    check_capability_access,
    get_current_capability,
    sign_capability_handle,
)

logger = logging.getLogger(__name__)

# Ceiling on a spawn capability's clock lifetime. The handle must outlive every attempt, retry and
# verification round of its spawn, so this is a generous bound on how long a leaked handle stays usable,
# not a per-attempt window.
_SPAWN_CAPABILITY_MAX_LIFETIME_SECONDS = 24 * 3600.0

_READ_ONLY_ACTIONS = frozenset({CapabilityAction.READ})
_WRITER_ACTIONS = frozenset({CapabilityAction.READ, CapabilityAction.WRITE, CapabilityAction.EXECUTE})
_VERIFIER_ACTIONS = frozenset({CapabilityAction.READ, CapabilityAction.EXECUTE})


def _mint_root_handle(subject_id: str, scope: ResourceScope, actions: frozenset[CapabilityAction]) -> CapabilityHandle:
    """Sign the handle of a spawn made by the top-level agent, which holds no handle to attenuate."""
    now = time.monotonic()
    unsigned = CapabilityHandle(
        handle_id=f"cap-sub-{uuid4().hex[:10]}",
        issuer_id="parent_agent",
        subject_id=subject_id,
        scope=scope,
        actions=actions,
        issued_at=now,
        expires_at=now + _SPAWN_CAPABILITY_MAX_LIFETIME_SECONDS,
    )
    return replace(unsigned, signature=sign_capability_handle(unsigned))


def _parent_context(parent_agent: object) -> dict[str, object]:
    """The context the parent's current run was built from; it holds the authoritative workspace."""
    context = getattr(parent_agent, "_last_context", None)
    return context if isinstance(context, dict) else {}


def parent_capability_handle() -> CapabilityHandle | None:
    """The handle the running agent was spawned under; ``None`` for the top-level agent, which holds none."""
    return get_current_capability()


def _resolve_context_path(raw: str, workspace: str) -> str | None:
    """Absolute, symlink-resolved form of a model-supplied path; relative paths resolve inside the workspace.

    ``None`` for anything that is not a usable path (empty, or text the filesystem API rejects such as an
    embedded NUL), so a malformed tool argument is dropped like any other unauthorized path.
    """
    path = os.path.expanduser(raw.strip())
    if not path:
        return None
    if not os.path.isabs(path):
        if not workspace:
            return None
        path = os.path.join(workspace, path)
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return None


def authorized_context_paths(parent_agent: object, context_files: list[str] | None, *, readonly: bool) -> list[str]:
    """Keep the model-supplied ``context_files`` the parent may itself reach without further approval.

    The paths come straight from a tool argument, so each one is judged by the parent's own path policy
    (forbidden zones, directories authorized by the user or the configuration, writable-ness for a
    writing child) and, for a spawned parent, by its own handle. Anything else is dropped and never
    widens the child's scope. Paths inside the workspace are already covered by the workspace scope.
    """
    if not context_files:
        return []

    from myrm_agent_harness.agent.security.checks import check_path_policy
    from myrm_agent_harness.agent.security.session_access import merge_path_policy_with_session_access
    from myrm_agent_harness.core.security.types import PathPolicy, PermissionAction, SecurityConfig

    workspace = str(_parent_context(parent_agent).get("workspace_path", "") or "")
    security_config = getattr(getattr(parent_agent, "config", None), "security_config", None)
    base_policy = security_config.path_policy if isinstance(security_config, SecurityConfig) else PathPolicy()
    policy = merge_path_policy_with_session_access(base_policy)
    parent_handle = parent_capability_handle()

    def reachable(path: str) -> bool:
        action, _ = check_path_policy(path, policy, workspace or None, require_write=not readonly)
        if action != PermissionAction.ALLOW:
            return False
        return parent_handle is None or check_capability_access(CapabilityAction.READ, path, handle=parent_handle)

    allowed: list[str] = []
    for raw in context_files:
        path = _resolve_context_path(str(raw), workspace)
        if path is not None and reachable(path):
            allowed.append(path)
        else:
            logger.warning("Dropped delegated context path outside the parent's authorized zones: %s", raw)
    return allowed


def derive_spawn_capability(
    *,
    parent_agent: object,
    agent_type: str,
    readonly: bool,
    context_files: list[str] | None = None,
) -> CapabilityHandle:
    """Mint the signed handle a child runs under.

    The scope is the parent's real workspace plus the authorized ``context_files``; the child's own
    context is not consulted because workspace isolation rewrites its ``workspace_path`` to a path the
    child does not actually run in. A spawned parent's handle bounds the child through attenuation, so
    a grandchild can never hold more than its parent.

    ``agent_type`` is the delegated target resolved by the caller. ``SubagentConfig`` carries the
    resolved settings but not the type id, so the subject must be passed in explicitly.

    Raises:
        AttenuationError: if the parent's handle has expired or cannot cover the requested child.
    """
    workspace = str(_parent_context(parent_agent).get("workspace_path", "") or "")
    paths = [f"{workspace.rstrip('/')}/**"] if workspace else []
    paths.extend(authorized_context_paths(parent_agent, context_files, readonly=readonly))
    scope = ResourceScope(paths=tuple(paths))
    actions = _READ_ONLY_ACTIONS if readonly else _WRITER_ACTIONS

    parent_handle = parent_capability_handle()
    if parent_handle is not None:
        return attenuate_capability(
            parent_handle,
            agent_type,
            target_scope=scope,
            target_actions=actions,
            ttl_seconds=_SPAWN_CAPABILITY_MAX_LIFETIME_SECONDS,
        )

    return _mint_root_handle(agent_type, scope, actions)


def derive_verifier_capability(verifier_type: str) -> CapabilityHandle:
    """Mint the handle a verifier runs under: the delegating agent's reach without WRITE.

    A verifier runs commands and reads what the worker produced, and never changes it. It keeps the path
    scope of the handle the delegating run is bound to. The top-level agent holds none, and a scope
    without path patterns constrains no path, so its verifier reads as widely as that agent does.

    Raises:
        AttenuationError: if the delegating agent's handle has expired.
    """
    parent_handle = parent_capability_handle()
    if parent_handle is None:
        return _mint_root_handle(verifier_type, ResourceScope(), _VERIFIER_ACTIONS)
    return attenuate_capability(
        parent_handle,
        verifier_type,
        target_actions=_VERIFIER_ACTIONS & parent_handle.actions,
        ttl_seconds=_SPAWN_CAPABILITY_MAX_LIFETIME_SECONDS,
    )
