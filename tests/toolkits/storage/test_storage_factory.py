"""Tests for storage configuration and factory.

Covers the single storage root derived from MYRM_DATA_DIR, provider creation, and the global provider singleton.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.storage.config import StorageConfig
from myrm_agent_harness.toolkits.storage.factory import (
    create_storage_provider,
    get_storage_provider,
    set_storage_provider,
)
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend


class TestStorageConfig:
    def test_base_path_derives_from_data_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_DATA_DIR", str(tmp_path))
        assert StorageConfig().get_base_path() == tmp_path.resolve() / "storage"

    def test_base_path_falls_back_to_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MYRM_DATA_DIR", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert StorageConfig().get_base_path() == tmp_path / ".myrm" / "storage"

    def test_relative_base_path_resolves_against_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        assert StorageConfig(base_path="rel/storage").get_base_path() == tmp_path.resolve() / "rel" / "storage"


class TestCreateStorageProvider:
    def test_create_with_explicit_config(self, tmp_path: Path) -> None:
        provider = create_storage_provider(StorageConfig(base_path=str(tmp_path / "root")))
        assert isinstance(provider, LocalStorageBackend)

    async def test_default_config_uses_global_storage_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "myrm_agent_harness.toolkits.storage.factory.storage_config",
            StorageConfig(base_path=str(tmp_path / "global")),
        )
        provider = create_storage_provider()
        await provider.write("probe.txt", b"x")
        assert (tmp_path / "global" / "probe.txt").read_bytes() == b"x"


class TestSingleStorageRoot:
    """Cloud sandboxes mount a single writable volume and expose it through MYRM_DATA_DIR.

    Every key family the product persists must land under {MYRM_DATA_DIR}/storage; a key routed anywhere else
    hits the read-only root filesystem and fails silently in production.
    """

    PRODUCTION_KEYS = (
        "files/uploads/file_1",
        "files/uploads/file_1.meta.json",
        "files/generated/file_2",
        "config/skills.json",
        "goals/goal_1.json",
        "goals_active/session_1",
        "goals_latest/session_1",
        "media/sandbox/image_1.png",
        "skills/prebuilt/skill_1/SKILL.md",
        "skills/local/skill_2/SKILL.md",
        "skills/workspace/skill_3/SKILL.md",
    )

    async def test_every_key_family_lands_under_data_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_DATA_DIR", str(tmp_path))
        provider = create_storage_provider(StorageConfig())

        for key in self.PRODUCTION_KEYS:
            await provider.write(key, b"payload")

        storage_root = tmp_path.resolve() / "storage"
        assert {path.relative_to(storage_root).as_posix() for path in storage_root.rglob("*") if path.is_file()} == set(
            self.PRODUCTION_KEYS
        )
        assert [p.name for p in tmp_path.iterdir()] == ["storage"]


class TestGlobalProvider:
    def test_set_and_get(self, tmp_path: Path) -> None:
        provider = LocalStorageBackend(tmp_path)
        set_storage_provider(provider)

        result = get_storage_provider()
        assert result is provider

        set_storage_provider(None)  # type: ignore[arg-type]
