"""Unit tests for Scoped Folder Permission Dialog and Sandbox Dynamic Mount Suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.core.security.scoped_folder_sandbox_mount import (
    DynamicSandboxMountManager,
    FolderAccessMode,
    MountLifecyclePolicy,
    SensitivePathGuard,
)


def test_sensitive_path_guard_blacklist(tmp_path: Path) -> None:
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".ssh").mkdir()
    (fake_home / ".aws").mkdir()
    (fake_home / "Documents").mkdir()

    guard = SensitivePathGuard(home_dir=fake_home)

    # 1. Prohibit mapping home directly
    res_home = guard.validate_path(str(fake_home))
    assert res_home.is_blocked is True
    assert res_home.matched_rule == "HOME_ROOT_PROHIBITED"

    # 2. Prohibit root filesystem
    res_root = guard.validate_path("/")
    assert res_root.is_blocked is True
    assert res_root.matched_rule == "FILESYSTEM_ROOT_PROHIBITED"

    # 3. Prohibit credential directories
    res_ssh = guard.validate_path(str(fake_home / ".ssh"))
    assert res_ssh.is_blocked is True
    assert "CREDENTIAL_ASSET" in (res_ssh.matched_rule or "")

    res_aws = guard.validate_path(str(fake_home / ".aws"))
    assert res_aws.is_blocked is True
    assert "CREDENTIAL_ASSET" in (res_aws.matched_rule or "")

    # 4. Prohibit system infrastructure
    res_etc = guard.validate_path("/etc")
    assert res_etc.is_blocked is True
    assert "SYSTEM_PREFIX" in (res_etc.matched_rule or "")

    # 5. Allow benign work folder
    res_work = guard.validate_path(str(fake_home / "Documents"))
    assert res_work.is_blocked is False
    assert res_work.matched_rule is None


def test_dynamic_sandbox_mount_manager_lifecycle(tmp_path: Path) -> None:
    fake_home = tmp_path / "user_home"
    fake_home.mkdir()
    docs_folder = fake_home / "Tax_Reports_2026"
    docs_folder.mkdir()

    guard = SensitivePathGuard(home_dir=fake_home)
    manager = DynamicSandboxMountManager(
        sandbox_base_mount="/sandbox/custom_mounts",
        path_guard=guard,
    )

    # 1. Grant folder access
    grant = manager.grant_folder_access(
        folder_path=str(docs_folder),
        access_mode=FolderAccessMode.READ_ONLY,
        lifecycle=MountLifecyclePolicy.EPHEMERAL_PER_SESSION,
        lease_seconds=3600.0,
    )
    assert grant.grant_id.startswith("grant-")
    assert grant.is_revoked is False
    assert grant.access_mode == FolderAccessMode.READ_ONLY
    assert grant.sandbox_mount_path == "/sandbox/custom_mounts/Tax_Reports_2026"

    # 2. Fetch Mount Spec
    spec = manager.get_mount_spec(grant.grant_id)
    assert spec is not None
    assert spec.read_only is True
    assert spec.source_host_path == str(docs_folder.resolve())
    assert spec.sandbox_target_path == "/sandbox/custom_mounts/Tax_Reports_2026"

    # 3. List active grants
    active = manager.list_active_grants()
    assert len(active) == 1
    assert active[0].grant_id == grant.grant_id

    # 4. Revoke grant
    revoked = manager.revoke_grant(grant.grant_id)
    assert revoked is True

    # After revocation, spec should be None and active list empty
    assert manager.get_mount_spec(grant.grant_id) is None
    assert len(manager.list_active_grants()) == 0
    assert len(manager.list_all_grants()) == 1


def test_dynamic_mount_blocked_on_sensitive_path(tmp_path: Path) -> None:
    fake_home = tmp_path / "home2"
    fake_home.mkdir()
    ssh_dir = fake_home / ".ssh"
    ssh_dir.mkdir()

    guard = SensitivePathGuard(home_dir=fake_home)
    manager = DynamicSandboxMountManager(path_guard=guard)

    with pytest.raises(PermissionError) as exc_info:
        manager.grant_folder_access(str(ssh_dir))

    assert "blocked by security policy" in str(exc_info.value)
