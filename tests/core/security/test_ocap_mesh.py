"""Unit tests for Object-Capability (OCap) zero-trust delegation mesh primitives.

[INPUT]
- myrm_agent_harness.core.security.ocap::*

[OUTPUT]
- Coverage for OCap signed tokens, attenuation rules, stateless handle validity, and guards.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from myrm_agent_harness.core.security.ocap import (
    AttenuationError,
    CapabilityAction,
    CapabilityDeniedError,
    CapabilityHandle,
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
    actions: frozenset[CapabilityAction] = frozenset(
        {CapabilityAction.READ, CapabilityAction.WRITE, CapabilityAction.EXECUTE}
    ),
    ttl: float = 3600.0,
) -> CapabilityHandle:
    now = time.monotonic()
    handle = CapabilityHandle(
        handle_id="cap-root-001",
        issuer_id="system-gate",
        subject_id=subject_id,
        scope=ResourceScope(paths=paths),
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
    tampered_actions = replace(root, actions=frozenset({CapabilityAction.READ}))
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
        target_scope=ResourceScope(paths=("/workspace/src/**", "/workspace/docs/**")),
        target_actions={CapabilityAction.READ},
        ttl_seconds=300.0,
    )

    assert child.subject_id == "child-worker-1"
    assert child.parent_handle_id == root.handle_id
    assert child.actions == frozenset({CapabilityAction.READ})
    assert child.expires_at <= root.expires_at
    assert verify_capability_signature(child) is True


def test_ocap_attenuation_blocks_action_elevation() -> None:
    root = _create_root_handle(actions=frozenset({CapabilityAction.READ, CapabilityAction.EXECUTE}))

    with pytest.raises(AttenuationError, match="Action elevation denied"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            ttl_seconds=300.0,
            target_actions={CapabilityAction.READ, CapabilityAction.WRITE},  # WRITE not in root
        )


def test_ocap_attenuation_blocks_path_elevation() -> None:
    root = _create_root_handle(paths=("/workspace/project-a/**",))

    # Attempting to access outside path
    with pytest.raises(AttenuationError, match="Path elevation denied"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            ttl_seconds=300.0,
            target_scope=ResourceScope(paths=("/workspace/project-b/**",)),
        )

    # Attempting to elevate to unrestricted
    with pytest.raises(AttenuationError, match="Child cannot have unrestricted"):
        attenuate_capability(
            parent=root,
            subject_id="rogue-child",
            ttl_seconds=300.0,
            target_scope=ResourceScope(paths=()),
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


def test_guard_enforcement_and_fail_closed() -> None:
    root = _create_root_handle(paths=("/workspace/project/**",))

    child = attenuate_capability(
        root,
        "worker",
        ttl_seconds=300.0,
        target_scope=ResourceScope(paths=("/workspace/project/src/**",)),
        target_actions={CapabilityAction.READ},
    )

    with capability_scope(child):
        assert get_current_capability() == child

        # Allowed read
        assert check_capability_access(CapabilityAction.READ, "/workspace/project/src/main.py") is True
        enforce_capability_access(CapabilityAction.READ, "/workspace/project/src/main.py")

        # Denied write (action not in handle)
        assert check_capability_access(CapabilityAction.WRITE, "/workspace/project/src/main.py") is False
        with pytest.raises(CapabilityDeniedError, match="Action 'write' denied"):
            enforce_capability_access(CapabilityAction.WRITE, "/workspace/project/src/main.py")

        # Denied read outside path boundary
        assert check_capability_access(CapabilityAction.READ, "/workspace/project/secret.env") is False
        with pytest.raises(CapabilityDeniedError, match="outside granted capability"):
            enforce_capability_access(CapabilityAction.READ, "/workspace/project/secret.env")


@pytest.mark.asyncio
async def test_file_ops_ocap_integration(tmp_path: pytest.TempPathFactory) -> None:
    from pathlib import Path

    from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
    from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor

    work_dir = Path(str(tmp_path))
    allowed_dir = work_dir / "allowed"
    secret_dir = work_dir / "secret"
    allowed_dir.mkdir()
    secret_dir.mkdir()

    allowed_file = allowed_dir / "doc.txt"
    allowed_file.write_text("allowed content", encoding="utf-8")

    secret_file = secret_dir / ".env"
    secret_file.write_text("SECRET_KEY=12345", encoding="utf-8")

    executor = LocalExecutor(config=ExecutionConfig(), workspace_path=str(work_dir))

    # 1. Unconstrained: can read both
    assert await executor.read_file(str(allowed_file)) == "allowed content"
    assert "SECRET_KEY" in await executor.read_file(str(secret_file))

    # 2. In restricted OCap scope (only allowed_dir)
    root = _create_root_handle(paths=(f"{work_dir}/**",))

    child = attenuate_capability(
        root,
        "worker-sandbox",
        ttl_seconds=300.0,
        target_scope=ResourceScope(paths=(f"{allowed_dir}/**",)),
        target_actions={CapabilityAction.READ, CapabilityAction.WRITE},
    )

    with capability_scope(child):
        # Reading allowed file succeeds
        assert await executor.read_file(str(allowed_file)) == "allowed content"

        # Reading secret file is physically blocked by OCap guard!
        with pytest.raises(CapabilityDeniedError, match="outside granted capability"):
            await executor.read_file(str(secret_file))

        # Writing to secret file is physically blocked!
        with pytest.raises(CapabilityDeniedError, match="outside granted capability"):
            await executor.write_file(str(secret_file), "hacked")

        # Writing to allowed file succeeds
        await executor.write_file(str(allowed_dir / "out.txt"), "hello")
        assert (allowed_dir / "out.txt").read_text() == "hello"

    # 3. An expired handle is denied end-to-end
    expired = replace(child, expires_at=time.monotonic() - 1.0)
    expired = replace(expired, signature=sign_capability_handle(expired))
    with capability_scope(expired), pytest.raises(CapabilityDeniedError, match="invalid or expired"):
        await executor.read_file(str(allowed_file))


def test_symlink_traversal_blocked_by_realpath(tmp_path: pytest.TempPathFactory) -> None:
    """Verify that a symlink pointing outside granted boundaries is fail-closed blocked."""
    import os
    from pathlib import Path

    from myrm_agent_harness.core.security.ocap.attenuation import _is_path_subscope

    base = Path(str(tmp_path))
    allowed_dir = base / "safe_zone"
    forbidden_dir = base / "forbidden_secrets"
    allowed_dir.mkdir()
    forbidden_dir.mkdir()

    secret_file = forbidden_dir / "master.key"
    secret_file.write_text("SUPER_SECRET_KEY", encoding="utf-8")

    # Create a malicious symlink inside safe_zone pointing to forbidden_secrets
    symlink_path = allowed_dir / "leak_link"
    try:
        os.symlink(str(secret_file), str(symlink_path))
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported in environment")

    # Lexically, leak_link is under safe_zone, but physically points to forbidden_secrets
    parent_scope = f"{allowed_dir}/**"
    # Must be blocked by realpath resolution!
    assert _is_path_subscope(str(symlink_path), parent_scope) is False


def test_guard_rejects_expired_and_tampered_handles() -> None:
    """Validity is the signature and the expiry; a handle needs no prior registration to be honoured."""
    valid = _create_root_handle(paths=("/workspace/**",))
    assert check_capability_access(CapabilityAction.READ, "/workspace/a.txt", handle=valid) is True

    expired = replace(valid, expires_at=time.monotonic() - 1.0)
    expired = replace(expired, signature=sign_capability_handle(expired))
    assert check_capability_access(CapabilityAction.READ, "/workspace/a.txt", handle=expired) is False
    with pytest.raises(CapabilityDeniedError, match="invalid or expired"):
        enforce_capability_access(CapabilityAction.READ, "/workspace/a.txt", handle=expired)

    widened = replace(valid, scope=ResourceScope(paths=("/",)))
    assert check_capability_access(CapabilityAction.READ, "/etc/hosts", handle=widened) is False
    unsigned = replace(valid, signature="")
    assert check_capability_access(CapabilityAction.READ, "/workspace/a.txt", handle=unsigned) is False


def test_guard_without_a_bound_handle_is_unconstrained() -> None:
    """The top-level agent holds no handle; its operations are not capability-checked."""
    assert check_capability_access(CapabilityAction.READ, "/any/path") is True
    enforce_capability_access(CapabilityAction.READ, "/any/path")


def test_guard_action_probe_without_target_only_checks_the_action() -> None:
    handle = _create_root_handle(actions=frozenset({CapabilityAction.READ}))

    assert check_capability_access(CapabilityAction.READ, handle=handle) is True
    assert check_capability_access(CapabilityAction.WRITE, handle=handle) is False
