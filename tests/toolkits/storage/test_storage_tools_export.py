"""Tests for storage_tools.py re-export module."""

from __future__ import annotations


def test_storage_tools_exports() -> None:
    from myrm_agent_harness.toolkits.storage import (
        FileInfo,
        StorageError,
        StorageProvider,
        create_storage_provider,
        get_storage_provider,
        set_storage_provider,
    )

    assert StorageProvider is not None
    assert StorageError is not None
    assert FileInfo is not None
    assert callable(create_storage_provider)
    assert callable(get_storage_provider)
    assert callable(set_storage_provider)
