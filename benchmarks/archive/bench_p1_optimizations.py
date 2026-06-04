"""P0-P1优化性能基准测试

验证以下优化的实际性能提升：
1. Skills LRU缓存 - 内存安全（maxsize=100, TTL=1h）
2. Checkpointer细粒度锁 - 并发性能提升3-5x
3. 增强降级文档 - Schema加载性能

运行方式：
    uv run python benchmarks/bench_p1_optimizations.py
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from myrm_agent_harness.agent.skills.runtime.loader import SkillMdLoader
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.toolkits.browser.checkpoint.incremental_checkpointer import (
    IncrementalSessionCheckpointer,
)


class MockSkillBackend:
    """Mock backend with configurable delay"""

    def __init__(self, delay_ms: float = 0):
        self.delay_ms = delay_ms
        self.call_count = 0

    async def get_skill_content(self, skill_name: str) -> str:
        self.call_count += 1
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000)
        return f"# {skill_name}\n\nMock content"


class MockCheckpointer:
    """Mock LangGraph checkpointer"""

    def __init__(self, delay_ms: float = 0):
        self.delay_ms = delay_ms
        self.aput_count = 0

    async def aput(self, config: dict[str, Any], checkpoint: Any, metadata: Any, new_versions: Any) -> dict[str, Any]:
        self.aput_count += 1
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000)
        return config


@pytest.mark.benchmark
class TestSkillsLRUCacheBenchmark:
    """Benchmark 1: Skills LRU缓存性能"""

    @pytest.mark.asyncio
    async def test_cache_hit_performance(self):
        """缓存命中性能（应该是微秒级）"""
        loader = SkillMdLoader()
        backend = MockSkillBackend(delay_ms=10)  # 10ms backend delay
        loader.set_backend(backend)

        skill = SkillMetadata(
            name="test-skill",
            description="Test",
            storage_skill_id="test-id",
        )

        # Warm up cache
        await loader.load_skill_details_by_metadata(skill)

        # Benchmark cache hit (100 iterations)
        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            await loader.load_skill_details_by_metadata(skill)
        duration = time.perf_counter() - start

        avg_time_ms = (duration / iterations) * 1000

        print("\n✅ Cache hit performance:")
        print(f"   Average: {avg_time_ms:.3f}ms per hit")
        print(f"   Total: {duration:.3f}s for {iterations} hits")

        # Cache hit should be much faster than backend (10ms)
        assert avg_time_ms < 1.0, f"Cache hit too slow: {avg_time_ms:.3f}ms"
        assert backend.call_count == 1  # Only initial load

    @pytest.mark.asyncio
    async def test_memory_bounded(self):
        """内存限制验证（100 skills上限）"""
        loader = SkillMdLoader()
        backend = MockSkillBackend()
        loader.set_backend(backend)

        # Load 200 skills
        for i in range(200):
            skill = SkillMetadata(
                name=f"skill-{i}",
                description=f"Skill {i}",
                storage_skill_id=f"id-{i}",
            )
            await loader.load_skill_details_by_metadata(skill)

        # Cache should be bounded
        cache_size = len(loader._skill_cache)
        assert cache_size <= 100, f"Cache size {cache_size} exceeds limit 100"

        print(f"\n✅ Memory bounded: {cache_size}/100 skills cached")


@pytest.mark.benchmark
class TestCheckpointerFineGrainedLockBenchmark:
    """Benchmark 2: Checkpointer细粒度锁并发性能"""

    @pytest.mark.asyncio
    async def test_parallel_checkpoint_speedup(self):
        """并行checkpoint性能提升（预期3-5x）"""
        mock_wrapped = MockCheckpointer(delay_ms=50)
        checkpointer = IncrementalSessionCheckpointer(mock_wrapped)

        checkpoint = {"v": 1, "id": "ckpt-1", "ts": "2024-01-01T00:00:00Z"}
        new_versions = {}

        async def save_thread(thread_idx: int):
            thread_id = f"thread-{thread_idx}"
            config = {"configurable": {"thread_id": thread_id}}
            metadata = {
                "browser": {
                    "session_hash": f"hash-{thread_idx}",
                }
            }
            await checkpointer.aput(config, checkpoint, metadata, new_versions)

        # Benchmark: 10 concurrent saves for different threads
        start = time.perf_counter()
        tasks = [asyncio.create_task(save_thread(i)) for i in range(10)]
        await asyncio.gather(*tasks)
        parallel_duration = time.perf_counter() - start

        # Calculate theoretical serialized time
        serialized_time = 10 * 0.05  # 10 saves * 50ms

        # Calculate speedup
        speedup = serialized_time / parallel_duration

        print("\n✅ Parallel checkpoint performance:")
        print(f"   Parallel: {parallel_duration:.3f}s")
        print(f"   Serialized (theoretical): {serialized_time:.3f}s")
        print(f"   Speedup: {speedup:.1f}x")

        # Verify speedup meets target (3-5x)
        assert speedup >= 3.0, f"Expected speedup >= 3x, got {speedup:.1f}x"
        assert mock_wrapped.aput_count == 10


@pytest.mark.benchmark
class TestEnhancedDegradedDocBenchmark:
    """Benchmark 3: 增强降级文档性能"""

    @pytest.mark.asyncio
    async def test_degraded_doc_generation_speed(self):
        """降级文档生成速度（含schema加载）"""
        loader = SkillMdLoader()

        # Create MCP skill with real browser tools
        mcp_meta = SkillMetadata(
            name="browser-skill",
            description="Browser automation",
            mcp=MCPSkillData(
                server="cursor-ide-browser",
                tools=["browser_click", "browser_navigate", "browser_snapshot"],
                config=[],
            ),
        )

        # Benchmark degraded doc generation (100 iterations)
        iterations = 100
        start = time.perf_counter()
        for _ in range(iterations):
            result = await loader._generate_degraded_skill_doc(mcp_meta)
        duration = time.perf_counter() - start

        avg_time_ms = (duration / iterations) * 1000

        print("\n✅ Degraded doc generation performance:")
        print(f"   Average: {avg_time_ms:.3f}ms per generation")
        print(f"   Total: {duration:.3f}s for {iterations} generations")

        # Should be fast (< 10ms) even with schema loading
        assert avg_time_ms < 10.0, f"Generation too slow: {avg_time_ms:.3f}ms"

        # Verify schema is included
        assert "Parameters:" in result or "Schema unavailable" in result
        assert "browser_click" in result

    @pytest.mark.asyncio
    async def test_schema_availability_rate(self):
        """Schema可用性测试（预期80%+）"""
        loader = SkillMdLoader()

        # Test with real MCP tools
        real_tools = [
            "browser_click",
            "browser_navigate",
            "browser_snapshot",
            "browser_type",
            "browser_fill",
        ]

        mcp_meta = SkillMetadata(
            name="browser-skill",
            description="Browser automation",
            mcp=MCPSkillData(
                server="cursor-ide-browser",
                tools=real_tools,
                config=[],
            ),
        )

        degraded = await loader._generate_degraded_skill_doc(mcp_meta)

        # Count how many tools have schema
        tools_with_schema = sum(
            1
            for tool in real_tools
            if f"#### `{tool}`" in degraded and "Parameters:" in degraded.split(f"#### `{tool}`")[1].split("####")[0]
        )

        availability_rate = tools_with_schema / len(real_tools)

        print("\n✅ Schema availability:")
        print(f"   Tools with schema: {tools_with_schema}/{len(real_tools)}")
        print(f"   Availability rate: {availability_rate:.0%}")

        # Verify meets target (80%+)
        assert availability_rate >= 0.8, f"Expected >= 80% availability, got {availability_rate:.0%}"


if __name__ == "__main__":
    print("=" * 60)
    print("P0-P1 优化性能基准测试")
    print("=" * 60)

    # Run benchmarks
    pytest.main(
        [
            __file__,
            "-v",
            "-m",
            "benchmark",
            "--tb=short",
        ]
    )
