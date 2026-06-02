"""性能benchmark：验证file_read优化的实际收益

运行方式：
    cd myrm-agent-harness
    source .venv/bin/activate
    pytest tests/agent/tools/benchmark_file_read.py -v -s
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest


@pytest.mark.asyncio
@pytest.mark.benchmark
async def test_benchmark_read_file_smart():
    """性能测试：智能自适应读取的实际收益"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import (
        read_file_chunked,
        read_file_preview,
        read_file_smart,
    )

    # 创建一个50MB测试文件
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        # 写入50万行，每行约100字符 ≈ 50MB
        for i in range(1, 500001):
            f.write(f"Line {i}: {'x' * 90}\n")

    try:
        print(f"\n{'=' * 60}")
        print(f"测试文件: {temp_path}")
        print(f"文件大小: {temp_path.stat().st_size / (1024 * 1024):.1f} MB")
        print(f"{'=' * 60}\n")

        # 1. 测试完整读取（原始方式）
        print("1. 完整读取（原始方式）:")
        start = time.time()
        async with __import__("aiofiles").open(temp_path, "r", encoding="utf-8", errors="replace") as f:
            _ = await f.read()
        elapsed_full = time.time() - start
        print(f"   耗时: {elapsed_full:.2f}s\n")

        # 2. 测试分块读取
        print("2. 分块读取（chunked）:")
        start = time.time()
        _ = await read_file_chunked(temp_path)
        elapsed_chunked = time.time() - start
        print(f"   耗时: {elapsed_chunked:.2f}s")
        print(f"   提升: {elapsed_full / elapsed_chunked:.1f}x\n")

        # 3. 测试预览模式
        print("3. 预览模式（preview）:")
        start = time.time()
        _ = await read_file_preview(temp_path)
        elapsed_preview = time.time() - start
        print(f"   耗时: {elapsed_preview:.2f}s")
        print(f"   提升: {elapsed_full / elapsed_preview:.1f}x\n")

        # 4. 测试智能选择
        print("4. 智能自适应（smart）:")
        start = time.time()
        _ = await read_file_smart(temp_path)
        elapsed_smart = time.time() - start
        print(f"   耗时: {elapsed_smart:.2f}s")
        print(f"   提升: {elapsed_full / elapsed_smart:.1f}x\n")

        # 5. 测试缓存
        print("5. LRU缓存（第2次读取）:")
        start = time.time()
        _ = await read_file_smart(temp_path, enable_cache=True)
        elapsed_cached = time.time() - start
        print(f"   耗时: {elapsed_cached:.4f}s")
        print(f"   提升: {elapsed_full / elapsed_cached:.1f}x\n")

        print(f"{'=' * 60}")
        print("总结:")
        print(f"  智能自适应: {elapsed_full:.2f}s → {elapsed_smart:.2f}s ({elapsed_full / elapsed_smart:.1f}x)")
        print(f"  LRU缓存: {elapsed_full:.2f}s → {elapsed_cached:.4f}s ({elapsed_full / elapsed_cached:.0f}x)")
        print(f"{'=' * 60}\n")

        # 验证：智能选择应有提升（注意：50MB文件本身已经很快）
        assert elapsed_smart <= elapsed_full, f"智能选择性能下降: {elapsed_full / elapsed_smart:.1f}x"

        print(" 性能验证通过：")
        print(f"   智能自适应比完整读取快 {elapsed_full / elapsed_smart:.1f}x")
        print(f"   LRU缓存比完整读取快 {elapsed_full / elapsed_cached:.0f}x")

    finally:
        temp_path.unlink()


if __name__ == "__main__":
    import asyncio

    asyncio.run(test_benchmark_read_file_smart())
