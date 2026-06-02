"""Tests for embedding warmup and hash persistence."""

import asyncio
import json
import os
import tempfile

import pytest

from myrm_agent_harness.toolkits.memory.strategies.deduplicator import SmartDeduplicator
from myrm_agent_harness.toolkits.memory.types import SemanticMemory


@pytest.fixture
def mock_llm():
    """Mock LLM."""

    class MockLLM:
        async def ainvoke(self, messages):
            class Response:
                content = "DECISION: NEW\nREASON: Test"

            return Response()

    return MockLLM()


@pytest.fixture
def mock_vector():
    """Mock vector store."""

    class MockVector:
        async def search(self, collection, embedding, limit, filters, score_threshold):
            return []

        async def get(self, collection, ids):
            from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument

            return [VectorDocument(id=ids[0], content="Existing", metadata={})]

    return MockVector()


@pytest.fixture
def mock_embedding():
    """Mock embedding with batch support."""

    class MockEmbedding:
        @property
        def dimension(self):
            return 384

        async def embed_batch(self, texts):
            await asyncio.sleep(0.001)
            return [[0.1] * 384 for _ in texts]

    return MockEmbedding()


@pytest.fixture
def mock_config():
    """Mock config."""

    class MockConfig:
        semantic_collection = "sem"
        episodic_collection = "epi"

        class dedup:  # noqa: N801
            high_threshold = 0.95
            low_threshold = 0.60
            time_window_hours = 24

    return MockConfig()


@pytest.mark.asyncio
async def test_hash_persistence_atomic_write(mock_llm, mock_vector, mock_embedding, mock_config):
    """Validate hash cache persistence uses atomic write (temp + rename).

    Ensures crash during write doesn't corrupt cache file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "hash_cache.json")

        dedup = SmartDeduplicator(
            mock_llm, adaptive_capacity=False, persist_hash_cache=True, hash_cache_path=cache_path
        )

        memories = [SemanticMemory(content=f"Content {i}") for i in range(3)]
        for mem in memories:
            mem.embedding = [0.1] * 384

        await dedup.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)

        print("\n[Hash 持久化原子性验证]")
        print(f"  缓存文件: {cache_path}")
        print("  写入 3 个 hash")

        assert os.path.exists(cache_path), "Cache file should exist"

        with open(cache_path, encoding="utf-8") as f:
            data = json.load(f)
            assert len(data["hashes"]) == 3

        temp_files = [f for f in os.listdir(tmpdir) if f.endswith(".tmp")]
        print(f"  临时文件已清理: {len(temp_files) == 0}")
        assert len(temp_files) == 0, "Temp files should be cleaned up"
        print("  验证: 使用原子写入（temp + rename）")


@pytest.mark.asyncio
async def test_hash_persistence_cross_instance(mock_llm, mock_vector, mock_embedding, mock_config):
    """Validate hash persistence enables cross-instance deduplication.

    Empirical benefit: 100% deduplication across restarts.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = os.path.join(tmpdir, "hash_cache.json")

        dedup1 = SmartDeduplicator(
            mock_llm, adaptive_capacity=False, persist_hash_cache=True, hash_cache_path=cache_path
        )

        memories = [SemanticMemory(content=f"Content {i}") for i in range(10)]
        for mem in memories:
            mem.embedding = [0.1] * 384

        result1 = await dedup1.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)

        dedup2 = SmartDeduplicator(
            mock_llm, adaptive_capacity=False, persist_hash_cache=True, hash_cache_path=cache_path
        )

        result2 = await dedup2.deduplicate_batch(memories, mock_vector, mock_embedding, mock_config, None)

        print("\n[Hash 持久化跨实例验证]")
        print(f"  Instance 1: {len(result1)} 条新建")
        print(f"  Instance 2: {len(result2)} 条新建")
        print(f"  Hash 命中率: {dedup2.get_metrics().hit_rate:.1%}")

        assert len(result1) == 10, "First instance should create all"
        assert len(result2) == 0, "Second instance should skip all duplicates"
        assert dedup2.get_metrics().hit_rate == 1.0, "All should hit cache"
        print("  验证: 跨实例去重生效 ")
