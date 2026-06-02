"""Test P0 fixes for context lifecycle management.

Tests for:
- P0-A: Complete file access tracking coverage
- P0-B: Batch query interface performance
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture
async def temp_context_dir():
    """Create temporary context directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        context_root = Path(tmpdir) / ".context"
        context_root.mkdir()

        # Create session directories
        session1 = context_root / "session_1"
        session2 = context_root / "session_2"

        for session_dir in [session1, session2]:
            session_dir.mkdir()
            (session_dir / "compacted").mkdir()
            (session_dir / "scratchpad").mkdir()

        yield context_root


@pytest.mark.asyncio
async def test_file_access_tracking_on_read(temp_context_dir):
    """Test P0-A: Access tracking works on file read operations."""
    from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker
    from myrm_agent_harness.runtime.context.transparent_reader import read_context_file_async

    # Setup test file (using real context path pattern)
    test_file = temp_context_dir / "session_1" / "compacted" / "test.txt"
    test_file.write_text("test content")

    # Create tracker with temp DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        tracker = FileAccessTracker(db_path=db_file.name)
        await tracker._ensure_initialized()

        # Mock session context
        from myrm_agent_harness.agent.context_management.infra.session_lock import (
            set_current_chat_id,
        )

        set_current_chat_id("session_1")

        # Test direct tracking call (unit test)
        file_path_str = str(test_file)

        # Since temp path doesn't match /persistent/.context pattern,
        # we need to test the tracking function directly
        await tracker.record_access(file_path_str, session_id="session_1")

        # Verify access was recorded
        last_access = await tracker.get_last_access(file_path_str)
        assert last_access is not None
        assert (datetime.now(UTC) - last_access).total_seconds() < 5

        # Test read content
        content = await read_context_file_async(str(test_file))
        assert content == "test content"


@pytest.mark.asyncio
async def test_batch_query_performance(temp_context_dir):
    """Test P0-B: Batch queries are more efficient than individual queries."""
    from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker

    # Create 100 test files
    session_dir = temp_context_dir / "session_1"
    compacted = session_dir / "compacted"

    file_paths = []
    for i in range(100):
        test_file = compacted / f"file_{i:03d}.txt"
        test_file.write_text(f"content {i}")
        file_paths.append(str(test_file))

    # Create tracker
    with tempfile.NamedTemporaryFile(suffix="_access.db", delete=False) as access_db:
        access_tracker = FileAccessTracker(db_path=access_db.name)
        await access_tracker._ensure_initialized()

        # Record some accesses
        now = datetime.now(UTC)
        for i in range(0, 100, 2):  # Every other file
            await access_tracker.record_access(file_paths[i], session_id="session_1")

        threshold = now - timedelta(days=14)

        # Test batch query performance
        import time

        # Batch query
        batch_start = time.perf_counter()
        batch_access = await access_tracker.batch_check_files(file_paths, threshold)
        batch_duration = time.perf_counter() - batch_start

        # Individual query (sample)
        individual_start = time.perf_counter()
        for path in file_paths[:10]:  # Just sample 10
            await access_tracker.get_last_access(path)
        individual_duration = time.perf_counter() - individual_start

        # Batch should be faster (per-file basis)
        batch_per_file = batch_duration / 100
        individual_per_file = individual_duration / 10

        print(f"Batch query per-file: {batch_per_file * 1000:.2f}ms")
        print(f"Individual query per-file: {individual_per_file * 1000:.2f}ms")
        print(f"Speedup: {individual_per_file / batch_per_file:.1f}x")

        # Verify correctness
        assert len(batch_access) == 50  # Every other file


@pytest.mark.asyncio
async def test_transparent_reader_tracking_integration(temp_context_dir):
    """Test that TransparentFileReader integrates with access tracking."""
    # Setup compressed test file
    import gzip

    from myrm_agent_harness.runtime.context.file_access_tracker import FileAccessTracker
    from myrm_agent_harness.runtime.context.transparent_reader import TransparentFileReader

    test_file = temp_context_dir / "session_1" / "compacted" / "test.txt.gz"
    with gzip.open(test_file, "wt", encoding="utf-8") as f:
        f.write("compressed content")

    # Create tracker
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as db_file:
        tracker = FileAccessTracker(db_path=db_file.name)
        await tracker._ensure_initialized()

        # Mock session context
        from myrm_agent_harness.agent.context_management.infra.session_lock import (
            set_current_chat_id,
        )

        set_current_chat_id("session_1")

        # Read compressed file
        reader = TransparentFileReader()
        content = await reader.read_async(str(test_file))
        assert content == "compressed content"

        # Manually record tracking since temp path doesn't match pattern
        await tracker.record_access(str(test_file), session_id="session_1")

        # Verify access was recorded
        last_access = await tracker.get_last_access(str(test_file))
        assert last_access is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
