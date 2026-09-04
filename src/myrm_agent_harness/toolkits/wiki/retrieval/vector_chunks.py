"""Shared wiki vector upsert helpers with embed-window-aware chunking.

[INPUT]
- retriever.embedding.window_policy (POS: embed window SSOT + EmbedInputTooLargeError)
- retriever.splitter.embed_budget::split_for_embedding (POS: embed-time chunking)
- memory.protocols.embedding::EmbeddingProtocol (POS: embed contract)
- memory.protocols.vector::VectorStoreProtocol (POS: vector store contract)

[OUTPUT]
- upsert_text_vectors, delete_text_vectors, collapse_vector_hits

[POS]
DRY embed+vector path for WikiIndexer, SidecarIndexMixin, and WikiAssetIndexer.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
    EmbedWindowPolicy,
    resolve_embed_window_policy,
    token_counter_for_model,
)
from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import (
    split_for_embedding,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol


def chunk_vector_id(parent_key: str, chunk_index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{parent_key}#chunk:{chunk_index}"))


def legacy_vector_id(parent_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, parent_key))


async def delete_text_vectors(
    vector: VectorStoreProtocol,
    collection_name: str,
    parent_key: str,
    *,
    metadata_key: str,
) -> None:
    """Remove legacy single-vector and multi-chunk vectors for *parent_key*."""
    if hasattr(vector, "delete_by_filter"):
        await vector.delete_by_filter(collection_name, {metadata_key: parent_key})
    if hasattr(vector, "delete"):
        ids = [legacy_vector_id(parent_key)]
        ids.extend(chunk_vector_id(parent_key, index) for index in range(128))
        with contextlib.suppress(Exception):
            await vector.delete(collection_name, ids)


def _validate_chunks_fit_window(chunks: list[str], policy: EmbedWindowPolicy, parent_key: str) -> None:
    """Fail loud if a chunk still exceeds the provider window after splitting.

    Counts in the model's own budget unit (o200k tokens for BPE, wordpiece estimate
    for bge/bce/nomic) so the guard never undercounts CJK input and silently passes
    an oversized chunk to the provider.
    """
    counter = token_counter_for_model(policy.model)
    for chunk in chunks:
        tokens = counter(chunk)
        if tokens > policy.max_input_tokens:
            raise EmbedInputTooLargeError(
                token_count=tokens,
                limit=policy.max_input_tokens,
                model=policy.model,
                parent_key=parent_key,
            )


async def upsert_text_vectors(
    *,
    embedding: EmbeddingProtocol,
    vector: VectorStoreProtocol,
    collection_name: str,
    parent_key: str,
    text: str,
    base_metadata: dict[str, str | list[str]],
    metadata_key: str,
) -> int:
    """Chunk, embed, and upsert vectors for *text*. Returns chunk count."""
    policy = resolve_embed_window_policy(embedding)
    chunks = split_for_embedding(text, policy)
    if not chunks:
        return 0

    _validate_chunks_fit_window(chunks, policy, parent_key)

    vectors = await embedding.embed_batch(chunks)
    if len(vectors) != len(chunks):
        raise RuntimeError(f"Embedding batch size mismatch for '{parent_key}': {len(vectors)} != {len(chunks)}")

    await delete_text_vectors(vector, collection_name, parent_key, metadata_key=metadata_key)

    docs: list[VectorDocument] = []
    for index, (chunk, vec) in enumerate(zip(chunks, vectors, strict=True)):
        metadata = dict(base_metadata)
        metadata[metadata_key] = parent_key
        metadata["chunk_index"] = index
        metadata["chunk_count"] = len(chunks)
        docs.append(
            VectorDocument(
                id=chunk_vector_id(parent_key, index),
                content=chunk,
                vector=vec,
                metadata=metadata,
            )
        )
    await vector.upsert(collection_name, docs)
    return len(docs)


def collapse_vector_hits(hits: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Keep the best score per parent key (multi-chunk vector collapse)."""
    best: dict[str, float] = {}
    for key, score in hits:
        best[key] = max(best.get(key, float("-inf")), score)
    ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
    return ranked
