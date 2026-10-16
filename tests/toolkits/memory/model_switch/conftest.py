"""Fixtures for the embedding-model switch tests: one embedded Qdrant, three model generations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.vector.base import VectorStore
from myrm_agent_harness.toolkits.vector.qdrant.factory import clear_embedded_stores, create_embedded_store


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def store() -> AsyncIterator[VectorStore]:
    """One embedded Qdrant for the module (cold start dominates); tests isolate by collection prefix."""
    await clear_embedded_stores()
    embedded = await create_embedded_store(path=":memory:")
    try:
        yield embedded
    finally:
        await embedded.close()
        await clear_embedded_stores()


@pytest.fixture
def prefix() -> str:
    return f"sw{uuid4().hex[:8]}"


def _config(prefix: str, model: str) -> MemoryConfig:
    return MemoryConfig(embedding_model=model, collection_prefix=prefix, blob_storage_enabled=False)


@pytest.fixture
def old_config(prefix: str) -> MemoryConfig:
    return _config(prefix, "old-model")


@pytest.fixture
def new_config(prefix: str) -> MemoryConfig:
    return _config(prefix, "new-model")


@pytest.fixture
def third_config(prefix: str) -> MemoryConfig:
    return _config(prefix, "third-model")
