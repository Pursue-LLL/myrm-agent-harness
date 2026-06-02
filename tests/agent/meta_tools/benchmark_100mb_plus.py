"""性能benchmark：验证100MB+文件的真实收益

运行方式：
    cd myrm-agent-harness
    source .venv/bin/activate
    python tests/agent/tools/benchmark_100mb_plus.py
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path


async def benchmark_large_files():
    """测试100-500MB文件的性能"""
    from myrm_agent_harness.agent.meta_tools.file_ops.streaming import (
        StreamingConfig,
        get_cache_stats,
        read_file_preview,
        read_file_smart,
        reset_cache_stats,
    )

    results = []

    # 测试3种文件大小：100MB, 200MB, 500MB
    test_sizes = [
        (100, 1_000_000, "100MB (1M lines)"),
        (200, 2_000_000, "200MB (2M lines)"),
        (500, 5_000_000, "500MB (5M lines)"),
    ]

    for _size_mb, num_lines, desc in test_sizes:
        print(f"\n{'=' * 70}")
        print(f"测试: {desc}")
        print(f"{'=' * 70}\n")

        # 创建测试文件
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            temp_path = Path(f.name)
            print("创建测试文件...")
            for i in range(1, num_lines + 1):
                f.write(f"Line {i}: {'x' * 90}\n")
                if i % 100000 == 0:
                    print(f"  已写入 {i:,} 行...")

        actual_size_mb = temp_path.stat().st_size / (1024 * 1024)
        print(f"文件创建完成: {actual_size_mb:.1f}MB\n")

        try:
            # 1. 完整读取（基准）
            print("1. 完整读取（基准）:")
            start = time.time()
            async with __import__("aiofiles").open(temp_path, "r", encoding="utf-8", errors="replace") as f:
                _ = await f.read()
            elapsed_full = time.time() - start
            print(f"   耗时: {elapsed_full:.2f}s\n")

            # 2. 预览模式
            print("2. 预览模式（preview, 前1000行）:")
            start = time.time()
            _ = await read_file_preview(temp_path)
            elapsed_preview = time.time() - start
            speedup_preview = elapsed_full / elapsed_preview
            print(f"   耗时: {elapsed_preview:.2f}s")
            print(f"   提升: {speedup_preview:.1f}x\n")

            # 3. 智能自适应
            print("3. 智能自适应（smart）:")
            start = time.time()
            _ = await read_file_smart(temp_path)
            elapsed_smart = time.time() - start
            speedup_smart = elapsed_full / elapsed_smart
            print(f"   耗时: {elapsed_smart:.2f}s")
            print(f"   提升: {speedup_smart:.1f}x\n")

            # 4. 缓存测试（重复读取）
            print("4. LRU缓存（第2次读取）:")
            reset_cache_stats()
            config = StreamingConfig(enable_cache=True)

            # 第一次（缓存miss）
            await read_file_smart(temp_path, config=config)

            # 第二次（缓存hit）
            start = time.time()
            _ = await read_file_smart(temp_path, config=config)
            elapsed_cached = time.time() - start
            speedup_cached = elapsed_full / elapsed_cached if elapsed_cached > 0 else float("inf")
            print(f"   耗时: {elapsed_cached:.4f}s")
            print(f"   提升: {speedup_cached:.0f}x")

            # 缓存统计
            stats = get_cache_stats()
            print(f"   命中率: {stats.hit_rate * 100:.1f}% (hits={stats.hits}, misses={stats.misses})\n")

            # 记录结果
            results.append(
                {
                    "size": desc,
                    "full": elapsed_full,
                    "preview": elapsed_preview,
                    "smart": elapsed_smart,
                    "cached": elapsed_cached,
                    "speedup_preview": speedup_preview,
                    "speedup_smart": speedup_smart,
                    "speedup_cached": speedup_cached,
                }
            )

        finally:
            temp_path.unlink()

    # 输出汇总表格
    print(f"\n{'=' * 70}")
    print("汇总结果")
    print(f"{'=' * 70}\n")

    print(f"{'文件大小':<20} {'完整读取':>10} {'预览模式':>10} {'智能选择':>10} {'LRU缓存':>10}")
    print(f"{'=' * 70}")
    for r in results:
        print(f"{r['size']:<20} {r['full']:>9.2f}s {r['preview']:>9.2f}s {r['smart']:>9.2f}s {r['cached']:>9.4f}s")

    print(f"\n{'文件大小':<20} {'预览提升':>10} {'智能提升':>10} {'缓存提升':>10}")
    print(f"{'=' * 70}")
    for r in results:
        print(f"{r['size']:<20} {r['speedup_preview']:>9.1f}x {r['speedup_smart']:>9.1f}x {r['speedup_cached']:>9.0f}x")

    print(f"\n{'=' * 70}\n")

    # 验证：preview模式应有显著提升
    for r in results:
        assert r["speedup_preview"] > 5, f"{r['size']}: preview模式未达到5x提升 ({r['speedup_preview']:.1f}x)"
        assert r["speedup_cached"] > 50, f"{r['size']}: 缓存未达到50x提升 ({r['speedup_cached']:.0f}x)"

    print(" 所有性能验证通过！")


if __name__ == "__main__":
    import asyncio

    asyncio.run(benchmark_large_files())
