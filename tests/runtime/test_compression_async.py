"""Tests for async compression functionality."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.runtime.compression import (
    ASYNC_COMPRESSION_THRESHOLD,
    compress_content,
    compress_content_async,
    decompress_content,
    get_adaptive_compression_level,
    shutdown_compression_executor,
)


class TestAdaptiveCompressionLevel:
    """Test adaptive compression level selection."""

    def test_small_file_uses_level_1(self) -> None:
        """Small files (<100KB) should use level 1 for speed."""
        assert get_adaptive_compression_level(30000) == 1  # 30KB
        assert get_adaptive_compression_level(50000) == 1  # 50KB
        assert get_adaptive_compression_level(99999) == 1  # ~100KB

    def test_large_file_uses_level_6(self) -> None:
        """Large files (≥100KB) should use level 6 for balanced speed/ratio."""
        assert get_adaptive_compression_level(102400) == 6  # 100KB
        assert get_adaptive_compression_level(200000) == 6  # 200KB
        assert get_adaptive_compression_level(1000000) == 6  # 1MB
        assert get_adaptive_compression_level(10000000) == 6  # 10MB


class TestAsyncCompression:
    """Test async compression functionality."""

    @pytest.mark.asyncio
    async def test_small_file_sync_path(self) -> None:
        """Small files should use synchronous compression."""
        content = "Hello World" * 1000  # ~11KB
        compressed = await compress_content_async(content)

        # Should produce valid compressed content
        assert len(compressed) < len(content)
        decompressed = decompress_content(compressed)
        assert decompressed.decode("utf-8") == content

    @pytest.mark.asyncio
    async def test_large_file_async_path(self) -> None:
        """Large files should use async compression."""
        # Create content larger than ASYNC_COMPRESSION_THRESHOLD (100KB)
        content = "A" * (ASYNC_COMPRESSION_THRESHOLD + 10000)  # ~110KB
        compressed = await compress_content_async(content)

        # Should produce valid compressed content
        assert len(compressed) < len(content)
        decompressed = decompress_content(compressed)
        assert decompressed.decode("utf-8") == content

    @pytest.mark.asyncio
    async def test_adaptive_level_selection(self) -> None:
        """Test adaptive compression level selection."""
        # Small content (should use level 1)
        small_content = "X" * 30000  # 30KB
        compressed_small = await compress_content_async(small_content, adaptive=True)
        assert len(compressed_small) < len(small_content)

        # Large content (should use level 9)
        large_content = "Y" * 600000  # 600KB
        compressed_large = await compress_content_async(large_content, adaptive=True)
        assert len(compressed_large) < len(large_content)

        # Level 9 should compress better than level 1 for repetitive content
        # (but this is not guaranteed for all content types)
        decompressed_small = decompress_content(compressed_small)
        decompressed_large = decompress_content(compressed_large)
        assert decompressed_small.decode("utf-8") == small_content
        assert decompressed_large.decode("utf-8") == large_content

    @pytest.mark.asyncio
    async def test_explicit_level_override(self) -> None:
        """Test explicit compression level override."""
        content = "Z" * 200000  # 200KB
        compressed_level_1 = await compress_content_async(content, level=1, adaptive=False)
        compressed_level_9 = await compress_content_async(content, level=9, adaptive=False)

        # Both should decompress correctly
        assert decompress_content(compressed_level_1).decode("utf-8") == content
        assert decompress_content(compressed_level_9).decode("utf-8") == content

        # Level 9 should compress better for repetitive content
        assert len(compressed_level_9) < len(compressed_level_1)

    @pytest.mark.asyncio
    async def test_bytes_input(self) -> None:
        """Test async compression with bytes input."""
        content_bytes = b"Test content" * 10000  # ~120KB
        compressed = await compress_content_async(content_bytes)

        assert len(compressed) < len(content_bytes)
        decompressed = decompress_content(compressed)
        assert decompressed == content_bytes

    @pytest.mark.asyncio
    async def test_concurrent_compression(self) -> None:
        """Test multiple concurrent compression operations."""
        contents = [f"Content {i}" * 15000 for i in range(5)]  # 5 files, ~120KB each

        # Compress all concurrently
        tasks = [compress_content_async(content) for content in contents]
        compressed_results = await asyncio.gather(*tasks)

        # All should compress successfully
        assert len(compressed_results) == 5
        for compressed, original in zip(compressed_results, contents, strict=False):
            assert len(compressed) < len(original)
            decompressed = decompress_content(compressed)
            assert decompressed.decode("utf-8") == original

    @pytest.mark.asyncio
    async def test_consistency_with_sync_compression(self) -> None:
        """Async compression should produce same results as sync compression."""
        content = "Consistency test" * 5000  # ~80KB

        # Compress synchronously
        sync_compressed = compress_content(content, level=6)

        # Compress asynchronously with same level
        async_compressed = await compress_content_async(content, level=6, adaptive=False)

        # Results should be identical
        assert sync_compressed == async_compressed

    def test_executor_shutdown(self) -> None:
        """Test executor shutdown cleanup."""
        # This should not raise any errors
        shutdown_compression_executor()

        # Multiple shutdowns should be safe
        shutdown_compression_executor()

    @pytest.mark.asyncio
    async def test_atexit_registration(self) -> None:
        """Test that thread pool is registered with atexit for automatic cleanup."""
        # Trigger executor creation
        content = "X" * 150000  # 150KB
        await compress_content_async(content)

        # Verify the executor was created and is not shutdown
        from myrm_agent_harness.runtime.compression import _compression_executor

        assert _compression_executor is not None
        assert not _compression_executor._shutdown

        # Cleanup for next tests
        shutdown_compression_executor()


@pytest.mark.asyncio
async def test_integration_async_compression_workflow() -> None:
    """Integration test: full async compression workflow."""
    # Simulate large tool output
    large_output = "<html>" + "A" * 200000 + "</html>"  # ~200KB HTML

    # Compress with adaptive level
    compressed = await compress_content_async(large_output, adaptive=True)

    # Should achieve good compression ratio
    compression_ratio = len(large_output) / len(compressed)
    assert compression_ratio > 2.0  # At least 2x compression for repetitive content

    # Should decompress correctly
    decompressed = decompress_content(compressed)
    assert decompressed.decode("utf-8") == large_output

    # Cleanup
    shutdown_compression_executor()
