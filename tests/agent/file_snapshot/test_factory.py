"""Tests for file snapshot factory — auto-selection and caching.

Covers: create_file_snapshot_store git detection, fallback to local store,
        caching behavior, get_cached_store, _default_store_base.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.file_snapshot.factory import (
    _default_store_base,
    create_file_snapshot_store,
    get_cached_store,
)
from myrm_agent_harness.agent.file_snapshot.local_store import LocalFileSnapshotStore
from myrm_agent_harness.agent.file_snapshot.shadow_git_store import ShadowGitSnapshotStore


@pytest.fixture(autouse=True)
def _reset_cached_store():
    """Clear factory cache between tests."""
    import myrm_agent_harness.agent.file_snapshot.factory as factory_mod

    factory_mod._cached_store = None
    yield
    factory_mod._cached_store = None


# ------------------------------------------------------------------
# _default_store_base
# ------------------------------------------------------------------


def test_default_store_base_uses_myrm_data_dir():
    with patch.dict("os.environ", {"MYRM_DATA_DIR": "/data/myrm"}, clear=False):
        base = _default_store_base()
    assert base == Path("/data/myrm/file_snapshots")


def test_default_store_base_fallback():
    with patch.dict("os.environ", {}, clear=True):
        base = _default_store_base()
    assert base == Path.home() / ".myrm" / "file_snapshots"


# ------------------------------------------------------------------
# create_file_snapshot_store — git available
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_shadow_git_when_git_available():
    with patch(
        "myrm_agent_harness.agent.file_snapshot.factory._detect_git",
        new_callable=AsyncMock,
        return_value=True,
    ):
        store = await create_file_snapshot_store()
    assert isinstance(store, ShadowGitSnapshotStore)


# ------------------------------------------------------------------
# create_file_snapshot_store — git absent
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_creates_local_store_when_git_absent():
    with patch(
        "myrm_agent_harness.agent.file_snapshot.factory._detect_git",
        new_callable=AsyncMock,
        return_value=False,
    ):
        store = await create_file_snapshot_store()
    assert isinstance(store, LocalFileSnapshotStore)


# ------------------------------------------------------------------
# caching behavior
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_factory_caches_result():
    with patch(
        "myrm_agent_harness.agent.file_snapshot.factory._detect_git",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_detect:
        store1 = await create_file_snapshot_store()
        store2 = await create_file_snapshot_store()

    assert store1 is store2
    mock_detect.assert_awaited_once()


# ------------------------------------------------------------------
# get_cached_store
# ------------------------------------------------------------------


def test_get_cached_store_returns_none_before_init():
    assert get_cached_store() is None


@pytest.mark.asyncio
async def test_get_cached_store_returns_instance_after_init():
    with patch(
        "myrm_agent_harness.agent.file_snapshot.factory._detect_git",
        new_callable=AsyncMock,
        return_value=True,
    ):
        store = await create_file_snapshot_store()

    assert get_cached_store() is store
