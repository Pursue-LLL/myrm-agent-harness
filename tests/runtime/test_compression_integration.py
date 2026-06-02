"""Integration tests for compression with context offload."""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.runtime.compression import (
    compress_content_async,
    decompress_content,
    get_adaptive_compression_level,
    shutdown_compression_executor,
)


@pytest.mark.asyncio
async def test_compression_performance_small_files() -> None:
    """Test compression performance for small files (<50KB)."""
    content = "Small file content" * 2000  # ~36KB

    start = time.perf_counter()
    compressed = await compress_content_async(content, adaptive=True)
    duration = time.perf_counter() - start

    # Should use level 1 (fast)
    expected_level = get_adaptive_compression_level(len(content))
    assert expected_level == 1

    # Should be very fast (<1ms for small files)
    assert duration < 0.01  # 10ms threshold

    # Should compress successfully
    assert len(compressed) < len(content)
    decompressed = decompress_content(compressed)
    assert decompressed.decode("utf-8") == content


@pytest.mark.asyncio
async def test_compression_performance_medium_files() -> None:
    """Test compression performance for medium files (50-500KB)."""
    content = "Medium file content" * 15000  # ~285KB

    start = time.perf_counter()
    compressed = await compress_content_async(content, adaptive=True)
    duration = time.perf_counter() - start

    # Should use level 6 (balanced)
    expected_level = get_adaptive_compression_level(len(content))
    assert expected_level == 6

    # Should be fast (<50ms for medium files)
    assert duration < 0.05  # 50ms threshold

    # Should compress successfully
    assert len(compressed) < len(content)
    decompressed = decompress_content(compressed)
    assert decompressed.decode("utf-8") == content


@pytest.mark.asyncio
async def test_compression_performance_large_files() -> None:
    """Test compression performance for large files (>100KB)."""
    content = "Large file content" * 50000  # ~950KB

    start = time.perf_counter()
    compressed = await compress_content_async(content, adaptive=True)
    duration = time.perf_counter() - start

    # Should use level 6 (balanced speed/ratio)
    expected_level = get_adaptive_compression_level(len(content))
    assert expected_level == 6

    # Should complete in reasonable time (<200ms for large files)
    assert duration < 0.2  # 200ms threshold

    # Should compress successfully
    assert len(compressed) < len(content)
    decompressed = decompress_content(compressed)
    assert decompressed.decode("utf-8") == content


@pytest.mark.asyncio
async def test_mixed_workload_performance() -> None:
    """Test compression performance with mixed file sizes."""
    # Create mixed workload
    small_files = ["Small" * 2000 for _ in range(5)]  # 5x ~10KB
    medium_files = ["Medium" * 15000 for _ in range(3)]  # 3x ~90KB
    large_files = ["Large" * 50000 for _ in range(2)]  # 2x ~250KB

    all_files = small_files + medium_files + large_files

    # Compress all concurrently
    start = time.perf_counter()
    tasks = [compress_content_async(content, adaptive=True) for content in all_files]
    compressed_results = await asyncio.gather(*tasks)
    duration = time.perf_counter() - start

    # All should compress successfully
    assert len(compressed_results) == 10

    # Should complete in reasonable time
    assert duration < 0.5  # 500ms threshold for 10 files

    # Verify all decompressed correctly
    for compressed, original in zip(compressed_results, all_files, strict=False):
        assert len(compressed) < len(original)
        decompressed = decompress_content(compressed)
        assert decompressed.decode("utf-8") == original

    # Cleanup
    shutdown_compression_executor()


@pytest.mark.asyncio
async def test_compression_ratio_by_content_type() -> None:
    """Test compression ratios for different content types."""
    # Highly repetitive HTML (should compress very well)
    html_content = "<html><body>" + "<div>Content</div>" * 10000 + "</body></html>"

    # JSON with repetitive structure
    json_content = '{"key": "value", "data": [' + '{"id": 1, "name": "test"},' * 5000 + "]}"

    # Code with moderate repetition
    code_content = "def function():\n    pass\n" * 5000

    # Compress all
    html_compressed = await compress_content_async(html_content, adaptive=True)
    json_compressed = await compress_content_async(json_content, adaptive=True)
    code_compressed = await compress_content_async(code_content, adaptive=True)

    # Calculate compression ratios
    html_ratio = len(html_content) / len(html_compressed)
    json_ratio = len(json_content) / len(json_compressed)
    code_ratio = len(code_content) / len(code_compressed)

    # HTML should compress best (high repetition)
    assert html_ratio > 10.0

    # JSON should compress well
    assert json_ratio > 5.0

    # Code should compress moderately
    assert code_ratio > 2.0

    # Verify decompression
    assert decompress_content(html_compressed).decode("utf-8") == html_content
    assert decompress_content(json_compressed).decode("utf-8") == json_content
    assert decompress_content(code_compressed).decode("utf-8") == code_content

    # Cleanup
    shutdown_compression_executor()


@pytest.mark.asyncio
async def test_async_non_blocking_behavior() -> None:
    """Test that async compression doesn't block event loop."""
    # Create large file that will use async compression
    large_content = "X" * 200000  # 200KB

    # Start compression
    compression_task = asyncio.create_task(compress_content_async(large_content, adaptive=True))

    # Should be able to do other work while compression runs
    other_work_done = False

    async def other_work() -> None:
        nonlocal other_work_done
        await asyncio.sleep(0.001)  # Simulate other async work
        other_work_done = True

    await asyncio.gather(compression_task, other_work())

    # Both should complete
    assert other_work_done
    compressed = compression_task.result()
    assert len(compressed) < len(large_content)

    # Cleanup
    shutdown_compression_executor()
