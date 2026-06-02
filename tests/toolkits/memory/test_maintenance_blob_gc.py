import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.maintenance import sweep_orphaned_blobs
from myrm_agent_harness.toolkits.memory.config import MemoryConfig


@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_disabled():
    config = MemoryConfig(embedding_model="test", blob_storage_enabled=False)
    vector = AsyncMock()
    assert await sweep_orphaned_blobs(vector, config) == 0

@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_no_dir(tmp_path):
    config = MemoryConfig(embedding_model="test", blob_storage_enabled=True, blob_storage_path=str(tmp_path / "nonexistent"))
    vector = AsyncMock()
    assert await sweep_orphaned_blobs(vector, config) == 0

@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_empty_dir(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()
    config = MemoryConfig(embedding_model="test", blob_storage_enabled=True, blob_storage_path=str(blob_dir))
    vector = AsyncMock()
    assert await sweep_orphaned_blobs(vector, config) == 0

@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_mtime_grace_period(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()

    # Create a file that is very recent (within 1 hour)
    recent_file = blob_dir / "recent.gz"
    recent_file.touch()

    # Create a file that is old (older than 1 hour)
    old_file = blob_dir / "old.gz"
    old_file.touch()
    os.utime(old_file, (time.time() - 4000, time.time() - 4000))

    config = MemoryConfig(embedding_model="test", blob_storage_enabled=True, blob_storage_path=str(blob_dir))

    vector = AsyncMock()
    # Mock scroll to return no active blobs
    vector.scroll.return_value = ([], None)

    deleted_count = await sweep_orphaned_blobs(vector, config)

    # Only the old file should be deleted
    assert deleted_count == 1
    assert recent_file.exists()
    assert not old_file.exists()

@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_scroll_failure(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()

    old_file = blob_dir / "old.gz"
    old_file.touch()
    os.utime(old_file, (time.time() - 4000, time.time() - 4000))

    config = MemoryConfig(embedding_model="test", blob_storage_enabled=True, blob_storage_path=str(blob_dir))

    vector = AsyncMock()
    # Mock scroll to raise an exception
    vector.scroll.side_effect = Exception("Network error")

    deleted_count = await sweep_orphaned_blobs(vector, config)

    # GC should abort and return 0, no files should be deleted
    assert deleted_count == 0
    assert old_file.exists()

@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_active_blob_kept(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()

    active_file = blob_dir / "active.gz"
    active_file.touch()
    os.utime(active_file, (time.time() - 4000, time.time() - 4000))

    orphan_file = blob_dir / "orphan.gz"
    orphan_file.touch()
    os.utime(orphan_file, (time.time() - 4000, time.time() - 4000))

    config = MemoryConfig(embedding_model="test", blob_storage_enabled=True, blob_storage_path=str(blob_dir))

    vector = AsyncMock()
    # Mock scroll to return the active blob
    mock_doc = MagicMock()
    mock_doc.metadata = {"raw_exchange": "blob://active"}
    vector.scroll.side_effect = [([mock_doc], None)]

    deleted_count = await sweep_orphaned_blobs(vector, config)

    # Only the orphan file should be deleted
    assert deleted_count == 1
    assert active_file.exists()
    assert not orphan_file.exists()

@pytest.mark.asyncio
async def test_sweep_orphaned_blobs_delete_failure(tmp_path):
    blob_dir = tmp_path / "blobs"
    blob_dir.mkdir()

    orphan_file = blob_dir / "orphan.gz"
    orphan_file.touch()
    os.utime(orphan_file, (time.time() - 4000, time.time() - 4000))

    config = MemoryConfig(embedding_model="test", blob_storage_enabled=True, blob_storage_path=str(blob_dir))

    vector = AsyncMock()
    vector.scroll.return_value = ([], None)

    with patch("pathlib.Path.unlink", side_effect=PermissionError("Permission denied")):
        deleted_count = await sweep_orphaned_blobs(vector, config)

    assert deleted_count == 0
    assert orphan_file.exists()
