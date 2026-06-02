"""测试Skills三级Fallback策略

验证SkillMdLoader在各种失败场景下的降级行为：
1. Primary失败 -> Tertiary降级文档
2. Backend异常 -> Tertiary降级文档
3. 缓存命中 -> Secondary快速返回
4. Fallback统计正确记录

Reference: MASTER_IMPLEMENTATION_ROADMAP.md §13.5
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from myrm_agent_harness.agent.skills.runtime.loader import SkillMdLoader
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.utils.lru_cache import LRUCache

if TYPE_CHECKING:
    pass


class MockSkillBackend:
    """Mock SkillBackend for testing"""

    def __init__(self, should_fail: bool = False, content: str | None = None):
        self.should_fail = should_fail
        self.content = content
        self.call_count = 0

    async def get_skill_content(self, skill_name: str) -> str:
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"Mock backend failure for {skill_name}")
        if self.content is None:
            raise ValueError(f"No content configured for {skill_name}")
        return self.content


@pytest.fixture
def loader() -> SkillMdLoader:
    """Create a fresh loader for each test"""
    return SkillMdLoader()


@pytest.fixture
def mcp_skill_meta() -> SkillMetadata:
    """MCP skill metadata fixture"""
    return SkillMetadata(
        name="test-mcp-skill",
        description="Test MCP skill for fallback testing",
        mcp=MCPSkillData(server="test-server", tools=["tool-one", "tool-two"], config=[]),
    )


@pytest.fixture
def storage_skill_meta() -> SkillMetadata:
    """Storage skill metadata fixture"""
    return SkillMetadata(
        name="test-storage-skill",
        description="Test storage skill for fallback testing",
        storage_skill_id="test-storage-id",
    )


class TestPrimaryFallback:
    """测试Primary加载路径"""

    @pytest.mark.asyncio
    async def test_mcp_skill_primary_success(self, loader: SkillMdLoader, mcp_skill_meta: SkillMetadata):
        """MCP技能从内存生成成功"""
        content = await loader.load_skill_details_by_metadata(mcp_skill_meta)

        assert content is not None
        assert len(content) > 0
        # MCP skill should generate content from memory with tools listed
        assert "tool_one" in content or "tool-one" in content
        assert "tool_two" in content or "tool-two" in content

        assert loader._skill_cache.contains(mcp_skill_meta.name)

        assert loader._fallback_count.get(mcp_skill_meta.name, 0) == 0

    @pytest.mark.asyncio
    async def test_storage_skill_primary_success(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """存储技能从backend加载成功"""
        backend = MockSkillBackend(content="# Test Storage Skill\n\nThis is test content.")
        loader.set_backend(backend)

        content = await loader.load_skill_details_by_metadata(storage_skill_meta)

        assert content is not None
        assert "Test Storage Skill" in content
        assert backend.call_count == 1

        assert loader._skill_cache.contains(storage_skill_meta.name)

        assert loader._fallback_count.get(storage_skill_meta.name, 0) == 0


class TestSecondaryFallback:
    """测试Secondary缓存路径"""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_primary(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """缓存命中时跳过Primary加载"""
        backend = MockSkillBackend(content="# Original Content")
        loader.set_backend(backend)

        # First load - hits primary
        content1 = await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert backend.call_count == 1

        # Second load - hits cache (secondary)
        content2 = await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert backend.call_count == 1  # No additional backend call
        assert content1 == content2

        assert loader._fallback_count.get(storage_skill_meta.name, 0) == 0


class TestTertiaryFallback:
    """测试Tertiary降级文档生成"""

    @pytest.mark.asyncio
    async def test_backend_failure_triggers_tertiary(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """Backend失败时生成降级文档"""
        backend = MockSkillBackend(should_fail=True)
        loader.set_backend(backend)

        content = await loader.load_skill_details_by_metadata(storage_skill_meta)

        # Should return degraded content, not None
        assert content is not None
        assert "DEGRADED MODE" in content
        assert storage_skill_meta.name in content

        assert loader._fallback_count.get(storage_skill_meta.name) == 1

    @pytest.mark.asyncio
    async def test_no_backend_triggers_tertiary(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """没有配置backend时生成降级文档"""
        content = await loader.load_skill_details_by_metadata(storage_skill_meta)

        assert content is not None
        assert "DEGRADED MODE" in content
        assert "unavailable" in content.lower()

        assert loader._fallback_count.get(storage_skill_meta.name) == 1

    @pytest.mark.asyncio
    async def test_degraded_doc_contains_metadata(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """降级文档包含基本元数据"""
        content = await loader.load_skill_details_by_metadata(storage_skill_meta)

        assert storage_skill_meta.name in content
        assert storage_skill_meta.description in content
        assert "DEGRADED MODE" in content

    @pytest.mark.asyncio
    async def test_degraded_mcp_skill_lists_tools(self, loader: SkillMdLoader, mcp_skill_meta: SkillMetadata):
        """降级的MCP技能文档列出工具及其schema（增强版）"""
        # Directly test the degraded generator
        degraded = await loader._generate_degraded_skill_doc(mcp_skill_meta)

        # Basic structure
        assert "DEGRADED MODE" in degraded
        assert mcp_skill_meta.mcp.server in degraded

        # Tool names should be present
        assert "tool-one" in degraded or "tool_one" in degraded
        assert "tool-two" in degraded or "tool_two" in degraded

        # Enhanced: Should contain schema information
        # Either full schema or fallback message
        has_schema = (
            "Parameters:" in degraded
            or "Schema" in degraded
            or "No parameters" in degraded
            or "Schema unavailable" in degraded
        )
        assert has_schema, "Degraded doc should include schema information"

        # Should have structured sections
        assert "## Available Tools" in degraded
        assert "## Notes" in degraded
        assert "80% functionality" in degraded or "enhanced schema" in degraded


class TestFallbackStatistics:
    """测试Fallback统计和监控"""

    @pytest.mark.asyncio
    async def test_fallback_count_increments(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """Fallback计数正确递增"""
        # First fallback
        await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert loader._fallback_count.get(storage_skill_meta.name) == 1

        loader._skill_cache.clear()

        await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert loader._fallback_count.get(storage_skill_meta.name) == 2

    @pytest.mark.asyncio
    async def test_get_fallback_stats(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """获取Fallback统计"""
        # Trigger fallback
        await loader.load_skill_details_by_metadata(storage_skill_meta)

        stats = loader.get_fallback_stats()
        assert storage_skill_meta.name in stats
        assert stats[storage_skill_meta.name] == 1

        stats[storage_skill_meta.name] = 999
        assert loader._fallback_count.get(storage_skill_meta.name) == 1

    @pytest.mark.asyncio
    async def test_clear_cache_resets_fallback_count(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """清除缓存时重置fallback计数"""
        # Trigger fallback
        await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert loader._fallback_count.get(storage_skill_meta.name) == 1

        loader.clear_cache()

        assert loader._fallback_count.get(storage_skill_meta.name, 0) == 0


class TestFallbackRecovery:
    """测试Fallback后的恢复"""

    @pytest.mark.asyncio
    async def test_recovery_after_backend_fixed(self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata):
        """Backend修复后能恢复正常加载"""
        # Start with failing backend
        failing_backend = MockSkillBackend(should_fail=True)
        loader.set_backend(failing_backend)

        # First load - triggers tertiary
        content1 = await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert "DEGRADED MODE" in content1
        assert loader._fallback_count.get(storage_skill_meta.name) == 1

        # Fix backend and clear cache
        working_backend = MockSkillBackend(content="# Fixed Content\n\nNow working!")
        loader.set_backend(working_backend)
        loader._skill_cache.clear()

        # Second load - should succeed via primary
        content2 = await loader.load_skill_details_by_metadata(storage_skill_meta)
        assert "DEGRADED MODE" not in content2
        assert "Fixed Content" in content2
        assert working_backend.call_count == 1

        # Fallback count should still be 1 (not incremented)
        assert loader._fallback_count.get(storage_skill_meta.name) == 1


class TestEdgeCases:
    """测试边缘情况"""

    @pytest.mark.asyncio
    async def test_empty_backend_content_triggers_tertiary(
        self, loader: SkillMdLoader, storage_skill_meta: SkillMetadata
    ):
        """Backend返回空内容时触发tertiary"""
        backend = MockSkillBackend(content="")
        loader.set_backend(backend)

        content = await loader.load_skill_details_by_metadata(storage_skill_meta)

        # Empty content should trigger tertiary
        assert "DEGRADED MODE" in content
        assert loader._fallback_count.get(storage_skill_meta.name) == 1

    @pytest.mark.asyncio
    async def test_multiple_skills_independent_fallback(self, loader: SkillMdLoader):
        """多个技能的fallback独立计数"""
        skill1 = SkillMetadata(name="skill-1", description="Skill 1", storage_skill_id="skill-1-id")
        skill2 = SkillMetadata(name="skill-2", description="Skill 2", storage_skill_id="skill-2-id")

        # Both trigger fallback
        await loader.load_skill_details_by_metadata(skill1)
        await loader.load_skill_details_by_metadata(skill2)

        # Independent counts
        assert loader._fallback_count.get("skill-1") == 1
        assert loader._fallback_count.get("skill-2") == 1

        loader._skill_cache.clear()
        await loader.load_skill_details_by_metadata(skill1)

        assert loader._fallback_count.get("skill-1") == 2
        assert loader._fallback_count.get("skill-2") == 1

    @pytest.mark.asyncio
    async def test_degraded_doc_always_returns_non_empty(self, loader: SkillMdLoader):
        """降级文档保证非空返回"""
        minimal_meta = SkillMetadata(
            name="minimal-skill",
            description="",  # Empty description
            storage_skill_id="minimal-id",
        )

        content = await loader.load_skill_details_by_metadata(minimal_meta)

        # Should still return valid content
        assert content is not None
        assert len(content) > 0
        assert "minimal-skill" in content
        assert "DEGRADED MODE" in content


class TestEnhancedDegradedDoc:
    """测试增强的降级文档（Schema支持）"""

    @pytest.mark.asyncio
    async def test_degraded_doc_includes_tool_schema(self, loader: SkillMdLoader):
        """降级文档包含工具schema（从registry获取）"""
        # Create MCP skill with known tools
        mcp_meta = SkillMetadata(
            name="test-schema-skill",
            description="Test schema extraction",
            mcp=MCPSkillData(server="test-server", tools=["test-tool"], config=[]),
        )

        # Generate degraded doc
        degraded = await loader._generate_degraded_skill_doc(mcp_meta)

        # Should contain structured sections
        assert "## Available Tools" in degraded
        assert "### Tools and Schemas" in degraded
        assert "#### `test-tool`" in degraded

        # Should attempt to include schema (either full or unavailable message)
        assert "Parameters:" in degraded or "Schema unavailable" in degraded

    @pytest.mark.asyncio
    async def test_degraded_doc_with_multiple_tools(self, loader: SkillMdLoader):
        """降级文档支持多个工具的schema"""
        mcp_meta = SkillMetadata(
            name="multi-tool-skill",
            description="Multiple tools",
            mcp=MCPSkillData(server="multi-server", tools=["tool-a", "tool-b", "tool-c"], config=[]),
        )

        degraded = await loader._generate_degraded_skill_doc(mcp_meta)

        # All tools should be listed
        assert "tool-a" in degraded
        assert "tool-b" in degraded
        assert "tool-c" in degraded

        # Should have structured format
        assert degraded.count("####") >= 3  # At least 3 tool headers

    @pytest.mark.asyncio
    async def test_degraded_doc_storage_skill_unchanged(self, loader: SkillMdLoader):
        """存储技能的降级文档保持简洁（无schema）"""
        storage_meta = SkillMetadata(name="storage-skill", description="Storage skill", storage_skill_id="storage-id")

        degraded = await loader._generate_degraded_skill_doc(storage_meta)

        # Storage skills don't have schema
        assert "## Usage" in degraded
        assert "storage-backed skill" in degraded
        assert "Parameters:" not in degraded  # No schema for storage skills


class TestCacheMetrics:
    """测试缓存可观测性指标"""

    @pytest.mark.asyncio
    async def test_cache_metrics_exposed(self, loader: SkillMdLoader):
        """验证缓存metrics可获取"""
        metrics = loader.get_cache_metrics()

        assert "skill_cache" in metrics
        assert "fallback_count_cache" in metrics

        skill_metrics = metrics["skill_cache"]
        assert "hits" in skill_metrics
        assert "misses" in skill_metrics
        assert "hit_rate" in skill_metrics
        assert "evictions" in skill_metrics
        assert "expirations" in skill_metrics
        assert "size" in skill_metrics
        assert "maxsize" in skill_metrics

    @pytest.mark.asyncio
    async def test_metrics_track_hits_misses(self, loader: SkillMdLoader):
        """验证metrics正确追踪命中和未命中"""
        backend = MockSkillBackend(content="# Test\n\nContent")
        loader.set_backend(backend)

        skill = SkillMetadata(name="test-skill", description="Test", storage_skill_id="test-id")

        # First load - miss (not in cache)
        await loader.load_skill_details_by_metadata(skill)
        metrics1 = loader.get_cache_metrics()
        assert metrics1["skill_cache"]["misses"] >= 1

        # Second load - hit (in cache)
        await loader.load_skill_details_by_metadata(skill)
        metrics2 = loader.get_cache_metrics()
        assert metrics2["skill_cache"]["hits"] >= 1
        assert metrics2["skill_cache"]["hit_rate"] > 0


class TestLRUCacheIntegration:
    """测试LRU缓存集成（内存安全）"""

    @pytest.mark.asyncio
    async def test_cache_size_limit_enforced(self, loader: SkillMdLoader):
        """缓存大小限制生效（防止内存泄漏）"""
        backend = MockSkillBackend(content="# Test Content")
        loader.set_backend(backend)

        # Load 105 skills (exceeds maxsize=100)
        for i in range(105):
            skill = SkillMetadata(name=f"skill-{i}", description=f"Skill {i}", storage_skill_id=f"id-{i}")
            await loader.load_skill_details_by_metadata(skill)

        # Cache should contain at most 100 items
        assert len(loader._skill_cache) <= 100

        # Oldest skills should be evicted
        assert not loader._skill_cache.contains("skill-0")
        assert not loader._skill_cache.contains("skill-1")

        assert loader._skill_cache.contains("skill-104")
        assert loader._skill_cache.contains("skill-103")

    @pytest.mark.asyncio
    async def test_cache_ttl_expiration(self, loader: SkillMdLoader):
        """缓存TTL过期后自动刷新"""
        import time

        backend = MockSkillBackend(content="# Original Content")
        loader.set_backend(backend)

        # Create loader with short TTL for testing
        test_loader = SkillMdLoader()
        test_loader._skill_cache = LRUCache(maxsize=100, ttl=1, id="test_cache")  # 1 second TTL
        test_loader.set_backend(backend)

        skill = SkillMetadata(name="ttl-test-skill", description="TTL test", storage_skill_id="ttl-id")

        # First load
        content1 = await test_loader.load_skill_details_by_metadata(skill)
        assert "Original Content" in content1
        assert backend.call_count == 1

        # Immediate second load - should hit cache
        await test_loader.load_skill_details_by_metadata(skill)
        assert backend.call_count == 1  # No new backend call

        # Wait for TTL expiration
        time.sleep(1.1)

        # Update backend content
        backend.content = "# Updated Content"

        # Third load - cache expired, should reload from backend
        content3 = await test_loader.load_skill_details_by_metadata(skill)
        assert "Updated Content" in content3
        assert backend.call_count == 2  # New backend call

    @pytest.mark.asyncio
    async def test_lru_eviction_order(self, loader: SkillMdLoader):
        """LRU驱逐顺序正确（最少使用的先驱逐）"""
        backend = MockSkillBackend(content="# Content")
        loader.set_backend(backend)

        # Create loader with small cache for testing
        test_loader = SkillMdLoader()
        test_loader._skill_cache = LRUCache(maxsize=3, ttl=3600, id="test_lru")
        test_loader.set_backend(backend)

        skills = [
            SkillMetadata(name=f"skill-{i}", description=f"Skill {i}", storage_skill_id=f"id-{i}") for i in range(4)
        ]

        # Load 3 skills
        for skill in skills[:3]:
            await test_loader.load_skill_details_by_metadata(skill)

        # Access skill-1 to make it recently used
        _ = await test_loader.load_skill_details_by_metadata(skills[1])

        # Load skill-3 (should evict skill-0, the least recently used)
        await test_loader.load_skill_details_by_metadata(skills[3])

        # skill-0 should be evicted
        assert not test_loader._skill_cache.contains("skill-0")

        assert test_loader._skill_cache.contains("skill-1")
        assert test_loader._skill_cache.contains("skill-2")
        assert test_loader._skill_cache.contains("skill-3")
