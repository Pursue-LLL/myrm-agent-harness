"""Tests for directory inode identity resolution and sync arbitration suite."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.inode_identity import (
    DeviceFilesystemKind,
    DirectoryIdentity,
    DirectoryIdentityGuard,
    IdentityMatchKind,
    InodeIdentityFacade,
    InodeIdentityResolver,
    SyncGuardAction,
    get_inode_identity_facade,
)


def test_resolve_real_directory(tmp_path: Path) -> None:
    """Ensure a valid local directory resolves physical device and inode metadata."""
    target_dir = tmp_path / "workspace_alpha"
    target_dir.mkdir(parents=True)

    resolver = InodeIdentityResolver()
    result = resolver.resolve(str(target_dir))

    assert result.is_accessible is True
    assert result.is_directory is True
    assert result.is_symlink is False
    assert result.identity is not None

    identity = result.identity
    assert identity.canonical_path == os.path.realpath(str(target_dir))
    assert identity.device_id != 0 or identity.inode_id != 0
    assert identity.birth_time_ns > 0
    assert identity.physical_key == f"{identity.device_id}:{identity.inode_id}"
    assert identity.fs_kind in (DeviceFilesystemKind.POSIX, DeviceFilesystemKind.WINDOWS)


def test_resolve_symlink_directory(tmp_path: Path) -> None:
    """Ensure symlinked directories preserve real_path and flag symlink correctly."""
    real_dir = tmp_path / "actual_store"
    real_dir.mkdir()
    link_dir = tmp_path / "symlink_store"

    try:
        os.symlink(real_dir, link_dir)
    except OSError:
        pytest.skip("Symlink creation not supported on current platform/privilege")

    resolver = InodeIdentityResolver()
    result = resolver.resolve(str(link_dir))

    assert result.is_accessible is True
    assert result.is_directory is True
    assert result.is_symlink is True
    assert result.identity is not None
    assert result.real_path == os.path.realpath(str(real_dir))
    assert result.identity.canonical_path == os.path.realpath(str(real_dir))


def test_custom_root_identity_signature(tmp_path: Path) -> None:
    """Ensure explicit .myrm_identity file content is preserved in root signature."""
    target_dir = tmp_path / "custom_id_ws"
    target_dir.mkdir()
    id_file = target_dir / ".myrm_identity"
    id_file.write_text("myrm-fixed-uuid-12345", encoding="utf-8")

    resolver = InodeIdentityResolver()
    result = resolver.resolve(str(target_dir))

    assert result.identity is not None
    assert result.identity.root_signature == "file:myrm-fixed-uuid-12345"


def test_sync_guard_brand_new_registration(tmp_path: Path) -> None:
    """Verify an unrecorded workspace directory receives REGISTER_NEW directive."""
    target_dir = tmp_path / "new_repo"
    target_dir.mkdir()

    guard = DirectoryIdentityGuard()
    decision = guard.evaluate(str(target_dir), known_identities=[])

    assert decision.action == SyncGuardAction.REGISTER_NEW
    assert decision.match_kind == IdentityMatchKind.BRAND_NEW
    assert decision.needs_database_relocation is False
    assert decision.identity is not None


def test_sync_guard_exact_match(tmp_path: Path) -> None:
    """Verify matching physical key and path receives PROCEED_INCREMENTAL directive."""
    target_dir = tmp_path / "existing_repo"
    target_dir.mkdir()

    facade = InodeIdentityFacade()
    init_res = facade.resolve(str(target_dir))
    assert init_res.identity is not None

    decision = facade.evaluate_sync(
        str(target_dir),
        known_identities=[init_res.identity],
    )

    assert decision.action == SyncGuardAction.PROCEED_INCREMENTAL
    assert decision.match_kind == IdentityMatchKind.EXACT_MATCH
    assert decision.needs_database_relocation is False


def test_sync_guard_directory_move_detection(tmp_path: Path) -> None:
    """Verify moved/renamed directory preserves memory lineage and requests relocation."""
    old_dir = tmp_path / "project_v1"
    old_dir.mkdir()

    facade = InodeIdentityFacade()
    init_res = facade.resolve(str(old_dir))
    assert init_res.identity is not None
    recorded_identity = init_res.identity

    # Rename directory physically on filesystem
    new_dir = tmp_path / "project_renamed"
    old_dir.rename(new_dir)

    # Evaluate new directory against old recorded identity
    decision = facade.evaluate_sync(
        str(new_dir),
        known_identities=[recorded_identity],
    )

    assert decision.action == SyncGuardAction.RELOCATE_AND_PROCEED
    assert decision.match_kind == IdentityMatchKind.MOVED_OR_RENAMED
    assert decision.needs_database_relocation is True
    assert decision.old_path == recorded_identity.canonical_path
    assert decision.new_path == os.path.realpath(str(new_dir))


def test_sync_guard_inode_reused_rebuild_warning(tmp_path: Path) -> None:
    """Verify same path with simulated different inode triggers REBUILD_WARNING."""
    target_dir = tmp_path / "recreated_dir"
    target_dir.mkdir()

    facade = InodeIdentityFacade()
    current_res = facade.resolve(str(target_dir))
    assert current_res.identity is not None

    # Synthesize fake old identity with same path but different inode
    old_fake_identity = DirectoryIdentity(
        canonical_path=current_res.identity.canonical_path,
        device_id=current_res.identity.device_id,
        inode_id=current_res.identity.inode_id + 999999,
        birth_time_ns=current_res.identity.birth_time_ns - 1000,
        root_signature="auto:fake_old_sig",
        fs_kind=current_res.identity.fs_kind,
    )

    decision = facade.evaluate_sync(
        str(target_dir),
        known_identities=[old_fake_identity],
    )

    assert decision.action == SyncGuardAction.REBUILD_WARNING
    assert decision.match_kind == IdentityMatchKind.INODE_REUSED
    assert decision.needs_database_relocation is False


def test_sync_guard_blocked_on_invalid_path(tmp_path: Path) -> None:
    """Verify non-existent or invalid paths are cleanly blocked."""
    missing_dir = tmp_path / "does_not_exist_at_all"

    guard = DirectoryIdentityGuard()
    decision = guard.evaluate(str(missing_dir), known_identities=[])

    assert decision.action == SyncGuardAction.BLOCKED
    assert "inaccessible" in decision.reason or "No such file" in decision.reason
    assert decision.identity is None


def test_singleton_accessor() -> None:
    """Ensure get_inode_identity_facade returns a reusable singleton instance."""
    inst1 = get_inode_identity_facade()
    inst2 = get_inode_identity_facade()
    assert inst1 is inst2
