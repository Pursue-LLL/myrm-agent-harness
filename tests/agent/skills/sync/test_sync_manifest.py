"""Tests for SkillSyncManifest — SQLite-backed sync state tracking."""

from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.sync.manifest import SkillSyncManifest


@pytest.fixture
def manifest(tmp_path: Path) -> SkillSyncManifest:
    db_path = tmp_path / "sync" / "manifest.db"
    return SkillSyncManifest(db_path)


def test_update_local_creates_entry(manifest: SkillSyncManifest) -> None:
    manifest.update_local("my_skill", "abc123")
    assert manifest.get_local_sha256("my_skill") == "abc123"


def test_pending_push_after_local_update(manifest: SkillSyncManifest) -> None:
    manifest.update_local("skill_a", "sha_a")
    manifest.update_local("skill_b", "sha_b")
    pending = manifest.get_pending_push()
    assert set(pending) == {"skill_a", "skill_b"}


def test_mark_pushed_clears_pending(manifest: SkillSyncManifest) -> None:
    manifest.update_local("skill_x", "sha_x")
    assert "skill_x" in manifest.get_pending_push()

    manifest.mark_pushed("skill_x")
    assert "skill_x" not in manifest.get_pending_push()


def test_update_remote_creates_pull_pending(manifest: SkillSyncManifest) -> None:
    manifest.update_remote("remote_skill", "sha_r", "2.0.0")
    pending_pull = manifest.get_pending_pull()
    assert "remote_skill" in pending_pull


def test_mark_synced_clears_all_pending(manifest: SkillSyncManifest) -> None:
    manifest.update_local("skill_z", "sha_z")
    manifest.mark_synced("skill_z", "sha_z")
    assert "skill_z" not in manifest.get_pending_push()
    assert "skill_z" not in manifest.get_pending_pull()


def test_get_sync_counts(manifest: SkillSyncManifest) -> None:
    manifest.update_local("a", "sha1")
    manifest.update_local("b", "sha2")
    manifest.update_remote("c", "sha3")
    counts = manifest.get_sync_counts()
    assert counts.get("local_only", 0) == 2
    assert counts.get("remote_ahead", 0) == 1


def test_last_sync_time(manifest: SkillSyncManifest) -> None:
    assert manifest.get_last_sync_time() is None
    manifest.set_last_sync_time()
    assert manifest.get_last_sync_time() is not None


def test_get_conflicts(manifest: SkillSyncManifest) -> None:
    assert manifest.get_conflicts() == []


def test_local_sha256_not_tracked(manifest: SkillSyncManifest) -> None:
    assert manifest.get_local_sha256("nonexistent") == ""


def test_persistence_across_instances(tmp_path: Path) -> None:
    db_path = tmp_path / "sync" / "persist.db"
    first = SkillSyncManifest(db_path)
    first.update_local("persistent", "sha_p")
    second = SkillSyncManifest(db_path)
    assert second.get_local_sha256("persistent") == "sha_p"
