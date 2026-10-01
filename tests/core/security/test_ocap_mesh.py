"""Unit tests for Object-Capability (OCap) zero-trust delegation mesh primitives.

[INPUT]
- myrm_agent_harness.core.security.ocap::*

[OUTPUT]
- 100% test coverage for OCap signed tokens, attenuation rules, cascading revocation, and guards.
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import replace

import pytest

from myrm_agent_harness.core.security.ocap import (
    AttenuationError,
    CapabilityAction,
    CapabilityDeniedError,
    CapabilityHandle,
    CapabilityRegistry,
    ResourceScope,
    attenuate_capability,
    capability_scope,
    check_capability_access,
    enforce_capability_access,
    get_current_capability,
    sign_capability_handle,
    verify_capability_signature,
)


def _create_root_handle(
    subject_id: str = "root-agent",
    paths: tuple[str, ...] = ("/workspace/**",),
    domains: tuple[str, ...] = ("api.github.com", "*.internal.net"),
    actions: frozenset[CapabilityAction] = frozenset(
        {CapabilityAction.READ, CapabilityAction.WRITE, CapabilityAction.EXECUTE, CapabilityAction.EGRESS}
    ),
    ttl: float = 3600.0,
) -> CapabilityHandle:
    now = time.monotonic()
    handle = CapabilityHandle(
        handle_id="cap-root-001",
        issuer_id="system-gate",
        subject_id=subject_id,
        scope=ResourceScope(paths=paths, domains=domains),
        actions=actions,
        issued_at=now,
        expires_at=now + ttl,
    )
    sig = sign_capability_handle(handle)
    return replace(handle, signature=sig)


def test_ocap_signature_and_tamper_proofing() -> None:
    root = _create_root_handle()
    assert verify_capability_signature(root) is True

    # Tampering with handle_id
    tampered_id = replace(root, handle_id="cap-fake")
    assert verify_capability_signature(tampered_id) is False

    # Tampering with actions
    tampered_actions = replace(root, actions=root.actions | {CapabilityAction.MCP})
    assert verify_capability_signature(tampered_actions) is False

    # Tampering with scope
    tampered_scope = replace(root, scope=ResourceScope(paths=("/",)))
    assert verify_capability_signature(tampered_scope) is False

    # Tampering with expiration
    tampered_exp = replace(root, expires_at=root.expires_at + 1000.0)
    assert verify_capability_signature(tampered_exp) is False


def test_ocap_attenuation_valid_subsets() -> None:
    root = _create_root_handle()

    child = attenuate_capability(
        parent=root,
        subject_id="child-worker-1",
        target_scope=ResourceScope(
            paths=("/workspace/src/**", "/workspace/docs/**"),
            domains=("api.github.com",),
        ),
        target_actions={CapabilityAction.READ},
        ttl_seconds=300.0,
    )

    assert child.subject_id == "child-worker-1"
    assert child.parent_handle_id == root.handle_id
    assert child.actions == frozenset({CapabilityAction.READ})
    assert child.expires_at <= root.expires_at
    assert verify_capability_signature(child) is True


def test_ocap_attenuation_blocks_action_elevation() -> None:
    root = _create_root_handle(
        actions=frozenset({CapabilityAction.READ, CapabilityAction.EXECUTE})
    )

    with pytest.raises(AttenuationError, match="Action elevation denied"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            target_actions={CapabilityAction.READ, CapabilityAction.WRITE},  # WRITE not in root
        )


def test_ocap_attenuation_blocks_path_elevation() -> None:
    root = _create_root_handle(paths=("/workspace/project-a/**",))

    # Attempting to access outside path
    with pytest.raises(AttenuationError, match="Path elevation denied"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            target_scope=ResourceScope(paths=("/workspace/project-b/**",)),
        )

    # Attempting to elevate to unrestricted
    with pytest.raises(AttenuationError, match="Child cannot have unrestricted paths"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            target_scope=ResourceScope(paths=()),
        )


def test_ocap_attenuation_blocks_domain_elevation() -> None:
    root = _create_root_handle(domains=("*.github.com",))

    with pytest.raises(AttenuationError, match="Domain elevation denied"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            target_scope=ResourceScope(
                paths=("/workspace/**",),
                domains=("attacker.com",),
            ),
        )


def test_ocap_attenuation_ttl_clamping() -> None:
    now = time.monotonic()
    root = _create_root_handle(ttl=50.0)

    # Request 300s, but root only has 50s left -> must be clamped to root's expires_at
    child = attenuate_capability(
        parent=root,
        subject_id="child-1",
        ttl_seconds=300.0,
        current_time=now,
    )
    assert child.expires_at <= root.expires_at


def test_cascading_revocation() -> None:
    registry = CapabilityRegistry()
    root = _create_root_handle()
    registry.register(root)

    child_1 = attenuate_capability(root, "child-1", ttl_seconds=500.0)
    registry.register(child_1)

    grandchild_1 = attenuate_capability(child_1, "grandchild-1", ttl_seconds=200.0)
    registry.register(grandchild_1)

    assert registry.is_valid(root) is True
    assert registry.is_valid(child_1) is True
    assert registry.is_valid(grandchild_1) is True

    # Revoke child_1 -> grandchild_1 must cascade into invalid
    revoked_count = registry.revoke(child_1.handle_id, reason="task_completed")
    assert revoked_count >= 2
    assert registry.is_valid(child_1) is False
    assert registry.is_valid(grandchild_1) is False
    # root is unaffected
    assert registry.is_valid(root) is True


def test_guard_enforcement_and_fail_closed() -> None:
    registry = CapabilityRegistry()
    root = _create_root_handle(paths=("/workspace/project/**",))
    registry.register(root)

    child = attenuate_capability(
        root,
        "worker",
        target_scope=ResourceScope(paths=("/workspace/project/src/**",)),
        target_actions={CapabilityAction.READ},
    )
    registry.register(child)

    with capability_scope(child):
        assert get_current_capability() == child

        # Allowed read
        assert check_capability_access(CapabilityAction.READ, "/workspace/project/src/main.py", registry=registry) is True
        enforce_capability_access(CapabilityAction.READ, "/workspace/project/src/main.py", registry=registry)

        # Denied write (action not in handle)
        assert check_capability_access(CapabilityAction.WRITE, "/workspace/project/src/main.py", registry=registry) is False
        with pytest.raises(CapabilityDeniedError, match="Action 'write' denied"):
            enforce_capability_access(CapabilityAction.WRITE, "/workspace/project/src/main.py", registry=registry)

        # Denied read outside path boundary
        assert check_capability_access(CapabilityAction.READ, "/workspace/project/secret.env", registry=registry) is False
        with pytest.raises(CapabilityDeniedError, match="outside granted capability"):
            enforce_capability_access(CapabilityAction.READ, "/workspace/project/secret.env", registry=registry)


def test_concurrent_registry_access() -> None:
    registry = CapabilityRegistry(num_shards=8)
    root = _create_root_handle()
    registry.register(root)

    def worker_task(idx: int) -> bool:
        child = attenuate_capability(
            root,
            f"worker-{idx}",
            target_scope=ResourceScope(paths=(f"/workspace/sub-{idx}/**",)),
            ttl_seconds=60.0,
        )
        registry.register(child)
        valid_before = registry.is_valid(child)
        if idx % 3 == 0:
            registry.revoke(child.handle_id)
            return valid_before and not registry.is_valid(child)
        return valid_before

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(worker_task, i) for i in range(100)]
        results = [f.result() for f in futures]

    assert all(results) is True
