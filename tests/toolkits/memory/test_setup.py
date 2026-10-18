from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig


@pytest.mark.asyncio
async def test_create_local_memory_manager(tmp_path: Path):
    base_path = tmp_path / "memory"

    embedding_config = EmbeddingConfig(
        model="openai/text-embedding-3-small", api_key="sk-test"
    )

    manager = await create_local_memory_manager(
        base_path=base_path, embedding_config=embedding_config
    )

    assert isinstance(manager, MemoryManager)

    # Verify directories were created
    assert base_path.exists()
    assert (base_path / "vector_store").exists()

    # Check that the manager has the expected stores
    assert (
        hasattr(manager, "_relational_store")
        or hasattr(manager, "relational_store")
        or hasattr(manager, "store")
    )
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_passes_memory_policy(tmp_path: Path):
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    mock_embedding_service.dimension = 768
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(return_value=True)

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ),
    ):
        manager = await create_local_memory_manager(
            base_path=base_path, embedding_config=embedding_config
        )

    assert isinstance(manager, MemoryManager)
    assert manager.user_id == "sandbox_user"
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_probes_dimension_when_missing(
    tmp_path: Path,
):
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    mock_embedding_service.dimension = 0
    mock_embedding_service.embed = AsyncMock(return_value=[0.1] * 384)
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 384])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(return_value=True)

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ) as mock_create_vector_store,
    ):
        manager = await create_local_memory_manager(
            base_path=base_path, embedding_config=embedding_config
        )

    mock_embedding_service.embed.assert_awaited_once_with("dimension probe")
    assert mock_create_vector_store.await_args.args[0].embedding_dimension == 384
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_falls_back_to_default_dimension_on_probe_failure(
    tmp_path: Path,
):
    """A failed probe sizes nothing: collections are created by their first write instead."""
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    mock_embedding_service.dimension = -1
    mock_embedding_service.embed = AsyncMock(side_effect=RuntimeError("probe failed"))
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 1536])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(return_value=True)

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ) as mock_create_vector_store,
    ):
        manager = await create_local_memory_manager(
            base_path=base_path, embedding_config=embedding_config
        )

    # The store default is not the model's size; the guess must never reach ensure/create.
    assert mock_create_vector_store.await_args.args[0].embedding_dimension == 1536
    mock_vector_store.ensure_collection.assert_not_awaited()
    mock_vector_store.create_named_vector_collection.assert_not_awaited()
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_probes_dimension_when_property_raises(
    tmp_path: Path,
):
    """Dimension property raising must fall through to the probe path, not crash setup."""
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    type(mock_embedding_service).dimension = PropertyMock(
        side_effect=RuntimeError("dimension not yet detected")
    )
    mock_embedding_service.embed = AsyncMock(return_value=[0.1] * 384)
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 384])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(return_value=True)

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ) as mock_create_vector_store,
    ):
        manager = await create_local_memory_manager(
            base_path=base_path, embedding_config=embedding_config
        )

    mock_embedding_service.embed.assert_awaited_once_with("dimension probe")
    assert mock_create_vector_store.await_args.args[0].embedding_dimension == 384
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_with_time_decay(tmp_path: Path):
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    mock_embedding_service.dimension = 768
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(return_value=True)

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ),
    ):
        manager = await create_local_memory_manager(
            base_path=base_path,
            embedding_config=embedding_config,
            time_decay_half_life_days=7.0,
        )

    assert isinstance(manager, MemoryManager)
    assert manager.config.forgetting is not None
    assert manager.config.forgetting.time_decay_half_life_days == 7.0
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_creates_the_conversation_collection_with_named_vectors(
    tmp_path: Path,
):
    """The conversation collection is created through the store API with raw/summary vectors."""
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    mock_embedding_service.dimension = 768
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(return_value=False)

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ),
    ):
        manager = await create_local_memory_manager(
            base_path=base_path, embedding_config=embedding_config
        )

    assert isinstance(manager, MemoryManager)
    mock_vector_store.create_named_vector_collection.assert_awaited_once_with(
        manager.config.conversation_collection, 768, names=("raw", "summary")
    )
    await manager.close()


@pytest.mark.asyncio
async def test_create_local_memory_manager_continues_when_collection_ensure_fails(
    tmp_path: Path,
):
    base_path = tmp_path / "memory"
    embedding_config = EmbeddingConfig(model="openai/text-embedding-3-small")
    mock_embedding_service = AsyncMock()
    mock_embedding_service.dimension = 768
    mock_embedding_service.embed_batch = AsyncMock(return_value=[[0.1] * 768])
    mock_vector_store = AsyncMock()
    mock_vector_store.collection_exists = AsyncMock(side_effect=RuntimeError("boom"))

    with (
        patch(
            "myrm_agent_harness.toolkits.memory.setup.get_embedding_service",
            return_value=mock_embedding_service,
        ),
        patch(
            "myrm_agent_harness.toolkits.memory.setup.create_vector_store",
            AsyncMock(return_value=mock_vector_store),
        ),
    ):
        manager = await create_local_memory_manager(
            base_path=base_path, embedding_config=embedding_config
        )

    assert isinstance(manager, MemoryManager)
    await manager.close()
