"""Opt-in verbatim capture track of ``auto_extract_memories``.

The orchestration contract is checked against a mocked manager. The end-to-end
tests run against a real SQLite + embedded Qdrant memory stack in which only the
embedding model and the extraction LLM are fakes: everything between
``auto_extract_memories`` and the stores is production code, including the BM25
sparse-mirror wrapper that ``create_local_memory_manager`` puts around the vector
store. The wrapper has no named-vector support, so conversation storage and
search work only because both address the backend beneath it.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

import myrm_agent_harness.toolkits.memory.setup as memory_setup
from myrm_agent_harness.agent._internals.memory_extraction import auto_extract_memories
from myrm_agent_harness.toolkits.memory.conversation_search.memory_provider import MemoryConversationSearchProvider
from myrm_agent_harness.toolkits.memory.conversation_search.types import ConversationSearchRequest
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType
from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.factory import create_vector_store

_DIM = 16
_TURNS = [
    "我最近在准备杭州到东京的出差行程，下周三出发，你帮我看看高铁和飞机怎么衔接比较合适？",
    "东京那边的酒店预算大概每晚一千二百元，希望离开会场近一点，最好步行十分钟以内。",
    "另外我对花生严重过敏，订餐的时候一定要提前备注，帮我整理一份日语的过敏说明吧。",
    "回程想改到周五晚上，周六要陪女儿参加幼儿园的亲子活动，时间不能耽误。",
]
_REPLY = (
    "好的，我来逐项帮你梳理。首先是交通衔接：建议提前一天到达机场附近，预留足够的安检和中转时间；"
    "其次是住宿选择：优先考虑会场步行范围内、评分较高且可免费取消的酒店；"
    "再次是饮食与健康：提前准备过敏说明卡并在订餐时再次确认；最后是行程汇总：我会按日期生成表格方便你随时查看。"
)


class _CountingEmbedding:
    """Deterministic embedding stand-in that counts every embedded text."""

    def __init__(self) -> None:
        self.texts = 0

    @property
    def dimension(self) -> int:
        return _DIM

    @staticmethod
    def _vector(text: str) -> list[float]:
        return [b / 255.0 for b in hashlib.sha256(text.encode()).digest()[:_DIM]]

    async def embed(self, text: str) -> list[float]:
        self.texts += 1
        return self._vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.texts += len(texts)
        return [self._vector(text) for text in texts]


class _NoMemoryLLM:
    """Extraction LLM stand-in that records calls and extracts nothing."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages: list[BaseMessage], *args: object, **kwargs: object) -> AIMessage:
        self.calls += 1
        return AIMessage(content='{"memories": []}')


@dataclass
class _Stack:
    manager: MemoryManager
    embedding: _CountingEmbedding
    llm: _NoMemoryLLM

    async def run_turns(self, count: int, *, enable_verbatim: bool | None = None) -> None:
        """Replay ``count`` chat turns through the post-turn extraction entry point."""
        history: list[BaseMessage] = []
        for user_text in _TURNS[:count]:
            options: dict[str, bool] = {} if enable_verbatim is None else {"enable_verbatim": enable_verbatim}
            await auto_extract_memories(
                user_text,
                history,
                self.manager,
                cast(BaseChatModel, self.llm),
                source_chat_id="chat-1",
                assistant_reply=_REPLY,
                **options,
            )
            history += [HumanMessage(content=user_text), AIMessage(content=_REPLY)]


@pytest.fixture(params=[True, False], ids=["approval-on", "approval-off"])
async def stack(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_Stack]:
    embedding = _CountingEmbedding()
    monkeypatch.setattr(memory_setup, "get_embedding_service", lambda _config: embedding)
    vector_store = await create_vector_store(
        VectorStoreConfig(mode=DeploymentMode.EMBEDDED, local_path=str(tmp_path / "vectors"), embedding_dimension=_DIM)
    )
    manager = await create_local_memory_manager(
        tmp_path,
        EmbeddingConfig(model="fake", api_key="test"),
        user_id="u1",
        approval_required=request.param,
        vector_store=vector_store,
    )
    yield _Stack(manager=manager, embedding=embedding, llm=_NoMemoryLLM())
    await manager.close()


async def test_default_extraction_runs_compressed_track_only(stack: _Stack) -> None:
    await stack.run_turns(3)

    assert stack.llm.calls == 3
    assert stack.embedding.texts == 0
    assert await stack.manager.count_memories(MemoryType.CONVERSATION) == 0
    assert await stack.manager.count_pending() == 0


async def test_opt_in_captures_exactly_the_current_exchange_each_turn(stack: _Stack) -> None:
    await stack.run_turns(len(_TURNS), enable_verbatim=True)

    assert stack.llm.calls == len(_TURNS)
    assert await stack.manager.count_memories(MemoryType.CONVERSATION) == len(_TURNS)
    assert await stack.manager.count_pending() == 0
    stored = await stack.manager.list_memories(MemoryType.CONVERSATION, limit=50)
    assert sorted(m.content for m in stored if isinstance(m, ConversationMemory)) == sorted(_TURNS)
    assert stack.embedding.texts == 2 * len(_TURNS)


async def test_opt_in_capture_is_searchable(stack: _Stack) -> None:
    await stack.run_turns(len(_TURNS), enable_verbatim=True)

    hits = await stack.manager.search(_TURNS[1], memory_types=[MemoryType.CONVERSATION], limit=3)

    assert hits
    assert hits[0].memory.content == _TURNS[1]


async def test_opt_in_capture_is_recalled_with_the_verbatim_exchange(stack: _Stack) -> None:
    """The recall provider must hand back the stored words, not just the summary."""
    await stack.run_turns(len(_TURNS), enable_verbatim=True)

    response = await MemoryConversationSearchProvider(stack.manager).search(
        ConversationSearchRequest(query=_TURNS[2], current_conversation_id="other-chat")
    )

    assert response.hits
    top = response.hits[0]
    assert top.summary == _TURNS[2]
    assert _TURNS[2] in top.snippet
    assert _REPLY in top.snippet


async def test_turn_without_user_text_stores_no_verbatim_exchange(stack: _Stack) -> None:
    """An image-only message has no user words, so the assistant reply alone is not an exchange."""
    await auto_extract_memories(
        [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}],
        [HumanMessage(content=_TURNS[0]), AIMessage(content=_REPLY)],
        stack.manager,
        cast(BaseChatModel, stack.llm),
        source_chat_id="chat-1",
        assistant_reply=_REPLY,
        enable_verbatim=True,
    )

    assert await stack.manager.count_memories(MemoryType.CONVERSATION) == 0
    assert stack.embedding.texts == 0


async def _extract_without_cards(manager: MagicMock, **options: object) -> None:
    """Run one extraction turn whose compressed track yields no memory cards."""
    with patch(
        "myrm_agent_harness.toolkits.memory.strategies.extractor.extract_memories_from_conversation",
        new_callable=AsyncMock,
        return_value=MagicMock(memories=[], extraction_time_ms=0.0),
    ):
        await auto_extract_memories(
            query="Tell me about Python's history and design philosophy in detail",
            chat_history=[
                HumanMessage(content="What is Python?"),
                AIMessage(content="A programming language."),
            ],
            memory_manager=manager,
            llm=AsyncMock(),
            assistant_reply="A" * 200,
            **options,
        )


async def test_verbatim_capture_is_off_by_default() -> None:
    manager = MagicMock()
    manager.last_cited_memory_ids = []
    manager.store_batch = AsyncMock(return_value=[])
    phases: list[str] = []

    async def observer(phase: str, status: object, **kwargs: object) -> None:
        phases.append(phase)

    await _extract_without_cards(manager, lifecycle_observer=observer)

    manager.store_batch.assert_not_awaited()
    assert "write" not in phases


async def test_verbatim_capture_stores_only_the_current_exchange_outside_approval() -> None:
    manager = MagicMock()
    manager.last_cited_memory_ids = []
    manager.store_batch = AsyncMock(return_value=[MagicMock()])

    await _extract_without_cards(manager, enable_verbatim=True)

    manager.store_batch.assert_awaited_once()
    (memories,), kwargs = manager.store_batch.await_args
    assert [m.content for m in memories] == ["Tell me about Python's history and design philosophy in detail"]
    assert kwargs == {"_bypass_approval": True}


@pytest.mark.parametrize(("stored", "expected"), [(1, "success"), (0, "skipped")])
async def test_verbatim_capture_reports_write_phase(stored: int, expected: str) -> None:
    manager = MagicMock()
    manager.last_cited_memory_ids = []
    manager.store_batch = AsyncMock(return_value=[MagicMock()] * stored)
    calls: list[tuple[str, str]] = []

    async def observer(phase: str, status: object, **kwargs: object) -> None:
        calls.append((phase, getattr(status, "value", str(status))))

    await _extract_without_cards(manager, enable_verbatim=True, lifecycle_observer=observer)

    assert ("write", expected) in calls


async def test_verbatim_failure_does_not_discard_the_compressed_track() -> None:
    manager = MagicMock()
    manager.last_cited_memory_ids = []
    manager.store_batch = AsyncMock(side_effect=RuntimeError("vector store down"))
    calls: list[tuple[str, str]] = []

    async def observer(phase: str, status: object, **kwargs: object) -> None:
        calls.append((phase, getattr(status, "value", str(status))))

    with patch(
        "myrm_agent_harness.toolkits.memory.strategies.extractor.extract_memories_from_conversation",
        new_callable=AsyncMock,
        return_value=MagicMock(memories=[], extraction_time_ms=0.0),
    ) as compressed_track:
        await auto_extract_memories(
            query="Tell me about Python's history and design philosophy in detail",
            chat_history=[],
            memory_manager=manager,
            llm=AsyncMock(),
            assistant_reply="A" * 200,
            enable_verbatim=True,
            lifecycle_observer=observer,
        )

    compressed_track.assert_awaited_once()
    assert ("write", "error") in calls
    assert ("extract", "success") in calls
    assert ("extract", "error") not in calls
