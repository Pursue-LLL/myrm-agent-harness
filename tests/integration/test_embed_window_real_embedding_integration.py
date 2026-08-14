"""Integration: real embedding window budget over a real HTTP embedding endpoint.

Covers the EmbeddingWindowDetectorDynamicChunkBudget changes end-to-end on a live
OpenAI-compatible embedding endpoint (the product supports any self-hosted
``api_base`` — the deterministic local server below is a real product usage, used
here because external embedding accounts have exhausted quota):

1. ``split_for_embedding`` splits long Chinese text by the wordpiece character budget
   (bge-m3 = 8192 window, 0.9 margin -> 7372 chars) instead of the o200k BPE budget.
2. Every produced chunk stays inside the real wordpiece window (no silent truncation).
3. ``CloudEmbedding.embed_batch`` runs the real LiteLLM HTTP path to the endpoint.
4. Oversized input fails loud with ``EmbedInputTooLargeError`` before any HTTP call.
5. Memory ``_fit_text_for_embedding`` truncates to the first fitting chunk, then embeds.
6. Real wiki ingest of a long Chinese document embeds every chunk within the window.

Critical path (chunk budget / window check / fail-loud) is never mocked.
"""

from __future__ import annotations

import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import _fit_text_for_embedding
from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import (
    CloudEmbedding,
)
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
    EmbedWindowPolicy,
    estimate_wordpiece_tokens,
    is_cjk_wordpiece_model,
)
from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import (
    split_for_embedding,
)
from myrm_agent_harness.toolkits.wiki.core.config import WikiConfig
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.indexer import WikiIndexer

pytestmark = [pytest.mark.integration, pytest.mark.timeout(180)]

_MODEL = "BAAI/bge-m3"
_PARA = "企业知识管理系统需要高质量的分块策略来保证检索准确性与语义连贯性。"


class _LocalEmbeddingHandler(BaseHTTPRequestHandler):
    _dimension = 1024

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/v1/models":
            self._send_json({"object": "list", "data": [{"id": _MODEL, "object": "model"}]})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) or b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json({"error": "invalid json"}, status=400)
            return

        texts = payload.get("input") or payload.get("texts")
        if not isinstance(texts, list):
            self._send_json({"error": "missing input list"}, status=400)
            return

        data = [
            {
                "object": "embedding",
                "index": index,
                "embedding": self._deterministic_vector(str(text)),
            }
            for index, text in enumerate(texts)
        ]
        self._send_json(
            {
                "object": "list",
                "data": data,
                "model": _MODEL,
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            }
        )

    @staticmethod
    def _deterministic_vector(text: str) -> list[float]:
        seed = hashlib.sha256(text.encode("utf-8")).hexdigest()
        vector: list[float] = []
        for i in range(_LocalEmbeddingHandler._dimension):
            digest = hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()
            vector.append(round(int(digest[:8], 16) / 0xFFFFFFFF * 2.0 - 1.0, 6))
        return vector


class _LocalEmbeddingServer:
    """Thread-backed OpenAI-compatible embedding endpoint on an ephemeral port."""

    def __init__(self) -> None:
        self.base_url = ""
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _LocalEmbeddingServer:
        self._server = HTTPServer(("127.0.0.1", 0), _LocalEmbeddingHandler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="test-embedding-server")
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None


def _long_chinese_text(chars: int) -> str:
    return (_PARA * (chars // len(_PARA) + 1))[:chars]


def _assert_every_chunk_inside_window(chunks: list[str]) -> None:
    policy = EmbedWindowPolicy.for_model(_MODEL)
    for chunk in chunks:
        estimate = estimate_wordpiece_tokens(chunk)
        assert estimate <= policy.max_input_tokens, (
            f"chunk of {len(chunk)} chars estimates {estimate} wordpiece tokens > window {policy.max_input_tokens}"
        )


@pytest.fixture
def _local_endpoint() -> str:
    """Live local OpenAI-compatible embedding endpoint (ephemeral port)."""
    with _LocalEmbeddingServer() as server:
        yield server.base_url


@pytest.fixture
def embedding(_local_endpoint: str) -> CloudEmbedding:
    """CloudEmbedding pointed at the live local endpoint (real HTTP path)."""
    return CloudEmbedding(model=_MODEL, api_key="local-test-key", api_base=_local_endpoint)


@pytest.mark.asyncio
async def test_real_long_chinese_text_splits_and_embeds(
    embedding: CloudEmbedding,
) -> None:
    """Long Chinese text splits into fitting chunks and all embed over HTTP."""
    assert is_cjk_wordpiece_model(_MODEL), "bge-m3 must route to the wordpiece path"
    policy = EmbedWindowPolicy.for_model(_MODEL)
    assert policy.max_input_tokens == 8192, "bge-m3 window must be 8192"

    text = _long_chinese_text(30_000)
    chunks = split_for_embedding(text, policy)

    assert len(chunks) >= 3, "30k chars must produce multiple chunks"
    for chunk in chunks:
        assert len(chunk) <= policy.effective_chunk_budget

    _assert_every_chunk_inside_window(chunks)

    vectors = await embedding.embed_batch(chunks)
    assert len(vectors) == len(chunks), "endpoint must return one vector per chunk"
    assert all(len(v) > 0 for v in vectors)


@pytest.mark.asyncio
async def test_real_every_chunk_stays_inside_wordpiece_window(
    embedding: CloudEmbedding,
) -> None:
    """Boundary: 3x window of Chinese text is never silently truncated."""
    policy = EmbedWindowPolicy.for_model(_MODEL)
    text = _long_chinese_text(policy.max_input_tokens * 3)
    chunks = split_for_embedding(text, policy)

    _assert_every_chunk_inside_window(chunks)

    vectors = await embedding.embed_batch(chunks)
    assert len(vectors) == len(chunks)
    dims = {len(v) for v in vectors}
    assert len(dims) == 1, "all returned vectors must share one dimension"


@pytest.mark.asyncio
async def test_real_oversized_input_fails_loud(embedding: CloudEmbedding) -> None:
    """Failure path: input beyond the wordpiece window raises before any HTTP call."""
    huge = _long_chinese_text(embedding.input_token_limit + 5_000)

    with pytest.raises(EmbedInputTooLargeError):
        await embedding.embed_batch([huge])


@pytest.mark.asyncio
async def test_real_memory_fit_truncates_then_embeds(embedding: CloudEmbedding) -> None:
    """Memory path: oversized text truncates to the first fitting chunk and embeds."""
    policy = EmbedWindowPolicy.for_model(_MODEL)
    text = _long_chinese_text(policy.effective_chunk_budget + 2_000)
    fitted = _fit_text_for_embedding(text, embedding)

    assert len(fitted) < len(text), "oversized text must be truncated"
    assert estimate_wordpiece_tokens(fitted) <= policy.max_input_tokens

    vector = await embedding.embed(fitted)
    assert len(vector) > 0


@pytest.mark.asyncio
async def test_real_wiki_ingest_long_chinese_document(embedding: CloudEmbedding, tmp_path: Path) -> None:
    """Real wiki ingest: long Chinese published doc splits and every chunk embeds in-window."""
    structure = WikiStructure(tmp_path)
    structure.ensure_structure()
    config = WikiConfig(enable_hybrid_search=True, enable_directory_sidecars=False)

    vector_store = AsyncMock()
    vector_store.collection_exists.return_value = False
    vector_store.create_collection = AsyncMock()
    vector_store.ensure_collection = AsyncMock()
    vector_store.upsert = AsyncMock()
    vector_store.delete_by_filter = AsyncMock()

    indexer = WikiIndexer(structure, config, vector_store=vector_store, embedding=embedding)

    body = _long_chinese_text(20_000)
    markdown = f"---\npublish_status: published\n---\n\n## Compiled Truth\n{body}"
    concept_path = structure.get_concept_file_path("real-embed-note")
    concept_path.write_text(markdown, encoding="utf-8")

    await indexer.upsert("real-embed-note", markdown)

    assert vector_store.upsert.await_count == 1
    docs = vector_store.upsert.await_args.args[1]
    assert len(docs) >= 2, "20k chars must split into multiple vector documents"
    _assert_every_chunk_inside_window([doc.content for doc in docs])


# ── 遗漏场景补充（2026-08-13 继续测阶段）────────────────────────────────


@pytest.mark.asyncio
async def test_real_bpe_model_long_text_splits_by_token_budget(
    _local_endpoint: str,
) -> None:
    """BPE model routes to the tiktoken token budget and embeds over real HTTP."""
    model = "text-embedding-3-small"
    assert not is_cjk_wordpiece_model(model), "text-embedding-3-small must stay on the BPE path"
    bpe = CloudEmbedding(model=model, api_key="local-test-key", api_base=_local_endpoint)
    policy = EmbedWindowPolicy.for_model(model)

    text = _long_chinese_text(30_000)
    chunks = split_for_embedding(text, policy)

    assert len(chunks) >= 2, "30k chars must produce multiple chunks on the BPE path"
    vectors = await bpe.embed_batch(chunks)
    assert len(vectors) == len(chunks)


@pytest.mark.asyncio
async def test_real_small_window_wordpiece_budget(_local_endpoint: str) -> None:
    """Small-window wordpiece model (bge-large-zh, 512 window) uses the 0.5 char budget."""
    model = "BAAI/bge-large-zh-v1.5"
    assert is_cjk_wordpiece_model(model)
    small = CloudEmbedding(model=model, api_key="local-test-key", api_base=_local_endpoint)
    policy = EmbedWindowPolicy.for_model(model)
    assert policy.max_input_tokens == 512
    assert policy.effective_chunk_budget == 256, "512 window x 0.5 margin = 256 chars"

    text = _long_chinese_text(5_000)
    chunks = split_for_embedding(text, policy)

    assert len(chunks) >= 3
    for chunk in chunks:
        assert len(chunk) <= policy.effective_chunk_budget
        assert estimate_wordpiece_tokens(chunk) <= policy.max_input_tokens

    vectors = await small.embed_batch(chunks)
    assert len(vectors) == len(chunks)


@pytest.mark.asyncio
async def test_real_korean_text_wordpiece_budget(_local_endpoint: str) -> None:
    """Korean on a Chinese BERT wordpiece model (bge-large-zh) never exceeds the window."""
    model = "BAAI/bge-large-zh-v1.5"
    korean = CloudEmbedding(model=model, api_key="local-test-key", api_base=_local_endpoint)
    policy = EmbedWindowPolicy.for_model(model)

    korean_text = "오늘 회의에서 진행 상황을 논의했고 다음 주 계획을 확정했습니다. " * 400
    chunks = split_for_embedding(korean_text, policy)

    assert len(chunks) >= 3, "long Korean text must split into multiple chunks"
    for chunk in chunks:
        estimate = estimate_wordpiece_tokens(chunk)
        assert estimate <= policy.max_input_tokens, (
            f"Korean chunk estimates {estimate} wordpiece tokens > window {policy.max_input_tokens}"
        )

    vectors = await korean.embed_batch(chunks)
    assert len(vectors) == len(chunks)


@pytest.mark.asyncio
async def test_real_mixed_language_text_never_exceeds_window(
    _local_endpoint: str,
) -> None:
    """Mixed zh/en/ko text on a wordpiece model stays inside the window after splitting."""
    model = "BAAI/bge-large-zh-v1.5"
    mixed = CloudEmbedding(model=model, api_key="local-test-key", api_base=_local_endpoint)
    policy = EmbedWindowPolicy.for_model(model)

    mixed_text = (
        "企业知识管理系统需要兼顾检索质量与性能，"
        "The retrieval quality depends on both the embedding model and the chunking strategy. "
        "오늘 회의에서 다음 주 계획을 논의했습니다. "
    ) * 120
    chunks = split_for_embedding(mixed_text, policy)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert estimate_wordpiece_tokens(chunk) <= policy.max_input_tokens

    vectors = await mixed.embed_batch(chunks)
    assert len(vectors) == len(chunks)


@pytest.mark.asyncio
async def test_real_store_semantic_long_memory_truncates_and_embeds(
    _local_endpoint: str,
) -> None:
    """Real memory store path: oversized semantic memory truncates to a fitting chunk."""
    from myrm_agent_harness.toolkits.memory._internal.storage import store_semantic
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.types import SemanticMemory

    model = "BAAI/bge-large-zh-v1.5"
    real_embedding = CloudEmbedding(model=model, api_key="local-test-key", api_base=_local_endpoint)
    policy = EmbedWindowPolicy.for_model(model)

    vector_store = AsyncMock()
    vector_store.upsert = AsyncMock()
    cache = AsyncMock()
    cache.get.return_value = None
    cache.put = AsyncMock()
    config = MemoryConfig(
        embedding_model=model,
        collection_prefix="test_memory",
        bm25_top_k=50,
        bm25_max_corpus_size=5000,
    )

    memory = SemanticMemory(
        id="mem-overflow",
        content=_long_chinese_text(policy.effective_chunk_budget + 3_000),
    )
    result = await store_semantic(memory, vector_store, config, real_embedding, cache)

    assert result.embedding is not None, "real embedding must succeed after truncation"
    assert result.embedding != [0.1] * 768, "embedding must come from the real HTTP path"
    vector_store.upsert.assert_awaited_once()
