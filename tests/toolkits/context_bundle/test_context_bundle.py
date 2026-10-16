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
async def test_facade_exposes_memory_and_harness_paths(tmp_path: Path) -> None:
    facade = ContextBundleFacade.from_state_dir(tmp_path, ensure_layout=True)
    assert facade.memory_path() == tmp_path / "memory"
    assert facade.harness_path() == tmp_path / "harness"
    assert facade.qdrant_path() == tmp_path / "qdrant"


@pytest.mark.asyncio
async def test_facade_health_reports_scene_paths(tmp_path: Path) -> None:
    facade = ContextBundleFacade.from_state_dir(tmp_path, ensure_layout=True)
    health = await facade.health()
    assert health.writable is True
    assert health.scene_paths[ContextScene.MEMORY.value] == str(tmp_path / "memory")
    assert set(health.scene_paths) == {ContextScene.MEMORY.value, ContextScene.WORKSPACE.value}


def test_migration_dry_run_lists_missing_manifest(tmp_path: Path) -> None:
    report = run_migration_dry_run(tmp_path)
    assert report.manifest_exists is False
    assert any(action.id == "write_manifest" for action in report.actions)


def test_apply_migration_writes_manifest(tmp_path: Path) -> None:
    apply_migration(tmp_path, spec=ContextBundleSpec())
    report = run_migration_dry_run(tmp_path)
    assert report.manifest_exists is True
    assert (tmp_path / "context_bundle_manifest.json").is_file()
