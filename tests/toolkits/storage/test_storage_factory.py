"""Tests for storage factory.

Covers create_storage_provider with LOCAL and PERSISTENT modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.storage.config import (
    LocalStorageConfig,
    PersistentStorageConfig,
    StorageConfig,
    StorageMode,
)
from myrm_agent_harness.toolkits.storage.factory import (
    create_storage_provider,
    get_storage_provider,
    set_storage_provider,
)
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend
from myrm_agent_harness.toolkits.storage.persistent import PersistentStorageBackend


class TestCreateStorageProvider:
    def test_create_local(self, tmp_path: Path) -> None:
        config = StorageConfig(
            mode=StorageMode.LOCAL,
            local=LocalStorageConfig(base_path=str(tmp_path / "local")),
        )
        provider = create_storage_provider(config)
        assert isinstance(provider, LocalStorageBackend)

    def test_create_persistent(self, tmp_path: Path) -> None:
        config = StorageConfig(
            mode=StorageMode.PERSISTENT,
            persistent=PersistentStorageConfig(
                persistent_path=str(tmp_path / "persistent"),
                workspace_path=str(tmp_path / "workspace"),
            ),
        )
        provider = create_storage_provider(config)
        assert isinstance(provider, PersistentStorageBackend)

    def test_invalid_mode_raises(self) -> None:
        config = StorageConfig(mode=StorageMode.LOCAL)
        config.mode = "invalid_mode"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="Unsupported storage mode"):
            create_storage_provider(config)


class TestGlobalProvider:
    def test_set_and_get(self, tmp_path: Path) -> None:
        provider = LocalStorageBackend(tmp_path)
        set_storage_provider(provider)

        result = get_storage_provider()
        assert result is provider

        set_storage_provider(None)  # type: ignore[arg-type]
