"""Harness unit tests for context bundle toolkit."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.context_bundle import (
    ContextBundleFacade,
    ContextBundleSpec,
    ContextScene,
    apply_migration,
    run_migration_dry_run,
)


@pytest.mark.asyncio
async def test_facade_exposes_memory_and_offload_paths(tmp_path: Path) -> None:
    facade = ContextBundleFacade.from_state_dir(tmp_path, ensure_layout=True)
    assert facade.memory_path() == tmp_path / "memory"
    assert facade.offload_root() == tmp_path / "harness" / ".context"
    assert facade.session_offload_dir("chat_1") == tmp_path / "harness" / ".context" / "chat_1"


@pytest.mark.asyncio
async def test_facade_health_reports_scene_paths(tmp_path: Path) -> None:
    facade = ContextBundleFacade.from_state_dir(tmp_path, ensure_layout=True)
    health = await facade.health()
    assert health.writable is True
    assert health.scene_paths[ContextScene.MEMORY.value] == str(tmp_path / "memory")


def test_migration_dry_run_lists_missing_manifest(tmp_path: Path) -> None:
    report = run_migration_dry_run(tmp_path)
    assert report.manifest_exists is False
    assert any(action.id == "write_manifest" for action in report.actions)


def test_apply_migration_writes_manifest(tmp_path: Path) -> None:
    apply_migration(tmp_path, spec=ContextBundleSpec())
    report = run_migration_dry_run(tmp_path)
    assert report.manifest_exists is True
    assert (tmp_path / "context_bundle_manifest.json").is_file()


def test_incognito_policy_blocks_memory_writes() -> None:
    from myrm_agent_harness.toolkits.context_bundle import IncognitoPolicy

    spec = ContextBundleSpec(incognito=IncognitoPolicy(enabled=True))
    assert spec.allows_persistent_write(ContextScene.MEMORY) is False
    assert spec.allows_persistent_write(ContextScene.WORKSPACE) is True
