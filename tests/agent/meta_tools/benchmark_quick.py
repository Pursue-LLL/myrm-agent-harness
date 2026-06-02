"""快速benchmark：验证preview模式真实价值（仅100MB）"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path


async def quick_benchmark():
    """快速测试100MB文件"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import (
        get_cache_stats,
        read_file_preview,
        read_file_smart,
        reset_cache_stats,
    )

    # 创建100MB文件
    print("创建100MB测试文件...")
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
        temp_path = Path(f.name)
        for i in range(1, 1_000_001):
            f.write(f"Line {i}: {'x' * 90}\n")

    actual_size = temp_path.stat().st_size / (1024 * 1024)
    print(f"文件大小: {actual_size:.1f}MB\n")

    try:
        # 1. 完整读取
        print("1. 完整读取（基准）:")
        start = time.time()
        async with __import__("aiofiles").open(temp_path, "r", encoding="utf-8", errors="replace") as f:
            _ = await f.read()
        elapsed_full = time.time() - start
        print(f"   耗时: {elapsed_full:.2f}s\n")

        # 2. 预览模式
        print("2. 预览模式（前1000行）:")
        start = time.time()
        _ = await read_file_preview(temp_path)
        elapsed_preview = time.time() - start
        speedup = elapsed_full / elapsed_preview
        print(f"   耗时: {elapsed_preview:.2f}s")
        print(f"   提升: {speedup:.1f}x\n")

        # 3. 智能自适应
        print("3. 智能自适应:")
        start = time.time()
        _ = await read_file_smart(temp_path)
        elapsed_smart = time.time() - start
        speedup_smart = elapsed_full / elapsed_smart
        print(f"   耗时: {elapsed_smart:.2f}s")
        print(f"   提升: {speedup_smart:.1f}x\n")

        # 4. 缓存测试（第一次：缓存miss）
        print("4. LRU缓存:")
        reset_cache_stats()

        # 第一次读取（缓存miss）
        _ = await read_file_smart(temp_path, enable_cache=True)

        # 第二次读取（缓存hit）
        start = time.time()
        _ = await read_file_smart(temp_path, enable_cache=True)
        elapsed_cached = time.time() - start
        speedup_cached = elapsed_full / elapsed_cached if elapsed_cached > 0 else float("inf")

        stats = get_cache_stats()
        print(f"   耗时: {elapsed_cached:.4f}s")
        print(f"   提升: {speedup_cached:.0f}x")
        print(f"   命中率: {stats.hit_rate * 100:.1f}%\n")

        # 验证（基于实测数据）
        # 100MB文件在SSD上很快（0.15s），优化空间有限
        assert speedup > 1.5, f"preview模式提升不足: {speedup:.1f}x < 1.5x"
        assert speedup_cached > 2, f"缓存提升不足: {speedup_cached:.0f}x < 2x"

        print(f"{'=' * 60}")
        print(" 性能验证通过！")
        print(f"  preview模式: {speedup:.1f}x提升")
        print(f"  LRU缓存: {speedup_cached:.0f}x提升")
        print(f"{'=' * 60}\n")

    finally:
        temp_path.unlink()


if __name__ == "__main__":
    import asyncio

    asyncio.run(quick_benchmark())
