"""file_read_tool streaming mode tests

测试file_read_tool的智能读取、缓存、压缩支持等功能。

Test Coverage:
1. 基础模式：preview/chunked/all
2. 智能自适应：read_file_smart()自动选择策略
3. GB级防御：>1GB文件拒绝
4. LRU缓存：重复读取加速
5. 压缩支持：.gz/.bz2自动解压
"""

from __future__ import annotations

import gzip
import tempfile
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_streaming_functions_preview_mode():
    """测试preview模式：读取前1000行+总行数"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import read_file_preview

    # 创建一个大文件（2000行）
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        for i in range(1, 2001):
            f.write(f"Line {i}\n")

    try:
        # 测试preview模式
        result = await read_file_preview(temp_path, max_lines=1000)

        # 验证：应包含前1000行
        assert "Line 1" in result
        assert "Line 1000" in result

        # 验证：应包含提示（简化版不估算总行数）
        assert "file continues" in result or "more lines" in result
        assert "Tip" in result

        # 验证：不应包含第1001行
        assert "Line 1001" not in result

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_streaming_functions_chunked_read():
    """测试stream模式：分块读取（防OOM）"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import read_file_chunked

    # 创建一个中等大小的文件（~1MB）
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        # 写入1万行，每行约100字符
        for i in range(1, 10001):
            f.write(f"Line {i}: {'x' * 90}\n")

    try:
        # 测试分块读取（chunk_size=1MB）
        result = await read_file_chunked(temp_path, chunk_size_mb=1)

        # 验证：应包含完整内容
        assert "Line 1" in result
        assert "Line 5000" in result
        assert "Line 10000" in result

        # 验证：总行数应正确
        lines = result.strip().split("\n")
        assert len(lines) == 10000

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_streaming_functions_estimate_lines():
    """测试快速估算文件行数"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import estimate_file_lines

    # 创建一个中等大小的文件（5000行）
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        for i in range(1, 5001):
            f.write(f"Line {i}\n")

    try:
        # 测试估算
        estimated = await estimate_file_lines(temp_path)

        # 验证：误差应<10%
        actual = 5000
        error_rate = abs(estimated - actual) / actual
        assert error_rate < 0.1, f"Error rate {error_rate:.1%} > 10% (estimated={estimated}, actual={actual})"

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_file_read_tool_auto_fallback():
    """测试file_read_tool的自动fallback：>100MB自动切换preview模式

    Note: 这是一个慢测试（需要创建100MB+文件），仅在需要时运行。
    """
    pytest.skip("Slow test: creates 100MB+ file. Run only when needed.")

    # TODO: 实现完整的集成测试
    # 1. 创建一个>100MB的测试文件
    # 2. 调用file_read_tool with mode='all'
    # 3. 验证自动fallback到preview模式
    # 4. 验证结果包含"Auto-fallback to preview mode"提示


@pytest.mark.asyncio
@pytest.mark.integration
async def test_file_read_tool_oom_protection():
    """测试file_read_tool的OOM防护：GB级文件不崩溃

    Note: 这是一个慢测试（需要创建GB级文件），仅在需要时运行。
    """
    pytest.skip("Slow test: creates GB-level file. Run only when needed.")

    # TODO: 实现完整的OOM防护测试
    # 1. 创建一个1GB+的测试文件
    # 2. 调用file_read_tool with mode='stream'
    # 3. 验证能正常读取，不OOM
    # 4. 验证内存占用<200MB


@pytest.mark.asyncio
async def test_read_file_smart_small_file():
    """测试read_file_smart：小文件（<10MB）完整读取"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import read_file_smart

    # 创建一个小文件（1MB）
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        # 写入1万行，每行约100字符
        for i in range(1, 10001):
            f.write(f"Line {i}: {'x' * 90}\n")

    try:
        result = await read_file_smart(temp_path)

        # 验证：应包含完整内容
        assert "Line 1" in result
        assert "Line 10000" in result
        lines = result.strip().split("\n")
        assert len(lines) == 10000

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_read_file_smart_gb_rejection():
    """测试read_file_smart：>1GB文件拒绝"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import FileTooLargeError, read_file_smart

    # 模拟一个>1GB的文件（不实际创建）
    # 使用稀疏文件（sparse file）技巧
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        # 写入少量数据
        f.write(b"test\n" * 100)
        # 使用seek创建稀疏文件（不占用实际磁盘空间）
        f.seek(2 * 1024 * 1024 * 1024 - 1)  # 2GB
        f.write(b"\0")

    try:
        # 验证：应抛出FileTooLargeError
        with pytest.raises(FileTooLargeError, match="exceeds.*GB limit"):
            await read_file_smart(temp_path)

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_read_compressed_file_gz():
    """测试压缩文件读取：.gz格式"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import read_file_smart_with_compression

    # 创建一个.gz压缩文件
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".txt.gz") as f:
        temp_path = Path(f.name)
        with gzip.open(f, "wt", encoding="utf-8") as gz:
            for i in range(1, 1001):
                gz.write(f"Compressed line {i}\n")

    try:
        # 读取压缩文件
        result = await read_file_smart_with_compression(temp_path)

        # 验证：应包含解压后的内容
        assert "Compressed line 1" in result
        assert "Compressed line 1000" in result
        lines = result.strip().split("\n")
        assert len(lines) == 1000

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_estimate_file_lines_fast():
    """测试快速行数估算（三点采样法）"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import estimate_file_lines_fast

    # 创建一个中等大小的文件（5000行）
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        for i in range(1, 5001):
            f.write(f"Line {i}\n")

    try:
        # 测试估算
        estimated = await estimate_file_lines_fast(temp_path)

        # 验证：误差应<15%（三点采样精度较低）
        actual = 5000
        error_rate = abs(estimated - actual) / actual
        assert error_rate < 0.15, f"Error rate {error_rate:.1%} > 15% (estimated={estimated}, actual={actual})"

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_streaming_config():
    """测试StreamingConfig配置"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import StreamingConfig, read_file_smart

    # 测试自定义配置
    config = StreamingConfig(
        absolute_max_mb=2048,  # 2GB
        cache_max_size=200,
    )

    assert config.absolute_max == 2048 * 1024 * 1024
    assert config.cache_max_size == 200

    # 测试配置注入
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        f.write("test\n" * 1000)

    try:
        result = await read_file_smart(temp_path, config=config)
        assert "test" in result
    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_cache_stats():
    """测试缓存统计"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import (
        get_cache_stats,
        read_file_smart,
        reset_cache_stats,
    )

    # 重置统计
    reset_cache_stats()

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        f.write("cache test\n" * 100)

    try:
        # 第一次读取（miss）
        _ = await read_file_smart(temp_path, enable_cache=True)
        stats = get_cache_stats()
        assert stats.misses == 1
        assert stats.hits == 0

        # 第二次读取（hit）
        _ = await read_file_smart(temp_path, enable_cache=True)
        stats = get_cache_stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.hit_rate == 0.5

        # 测试to_dict()
        stats_dict = stats.to_dict()
        assert stats_dict["hits"] == 1
        assert stats_dict["misses"] == 1
        assert stats_dict["hit_rate"] == 0.5

    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_read_compressed_bz2():
    """测试.bz2压缩文件读取"""
    import bz2

    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import read_file_smart_with_compression

    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".bz2") as f:
        temp_path = Path(f.name)
        with bz2.open(f, "wt", encoding="utf-8") as bz:
            for i in range(1, 101):
                bz.write(f"BZ2 line {i}\n")

    try:
        result = await read_file_smart_with_compression(temp_path)
        assert "BZ2 line 1" in result
        assert "BZ2 line 100" in result
    finally:
        temp_path.unlink()


@pytest.mark.asyncio
async def test_read_file_smart_with_config_limits():
    """测试配置限制生效"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import (
        FileTooLargeError,
        StreamingConfig,
        read_file_smart,
    )

    # 创建一个小配置（1MB限制）
    config = StreamingConfig(absolute_max_mb=1)

    # 创建一个2MB文件
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        for i in range(1, 20001):  # 约2MB
            f.write(f"Line {i}: {'x' * 90}\n")

    try:
        # 验证：应抛出FileTooLargeError（因为配置限制1MB）
        with pytest.raises(FileTooLargeError):
            await read_file_smart(temp_path, config=config)
    finally:
        temp_path.unlink()
