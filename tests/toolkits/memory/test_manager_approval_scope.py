"""Approval resolves the proposal's target within the reviewer's namespaces and never fakes success."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import PendingTargetChangedError, get_from_vector
from myrm_agent_harness.toolkits.memory._internal.storage_converters import semantic_to_doc
from myrm_agent_harness.toolkits.memory._internal.storage_search import search_semantic
from myrm_agent_harness.toolkits.memory.config import AgentMemoryPolicy, MemoryScopeLevel
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
    SemanticMemory,
)

_ACTIONS = [PendingResolutionAction.CORRECT, PendingResolutionAction.DELETE]


@pytest.fixture(autouse=True)
def _no_content_scan():
    with patch("myrm_agent_harness.toolkits.memory._internal.write_service.scan_and_clean_memory") as mock:
        mock.return_value = None
        yield mock


@pytest.fixture
def docs(mock_vector_store) -> dict[str, VectorDocument]:
    """A dict-backed vector store so writes made by one manager are visible to another."""
    store: dict[str, VectorDocument] = {}

    async def _upsert(_collection, documents):
        for doc in documents:
            store[doc.id] = doc
        return [doc.id for doc in documents]

    async def _get(_collection, ids):
        return [store[i] for i in ids if i in store]

    mock_vector_store.upsert.side_effect = _upsert
    mock_vector_store.get.side_effect = _get
    mock_vector_store.search.return_value = []
    return store


@pytest.fixture
def make_manager(mock_vector_store, mock_relational_store, mock_embedding, memory_config):
    def _make(**scope) -> MemoryManager:
        return MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=False,
            **scope,
        )

    return _make


def _queue(mock_relational_store, action: PendingResolutionAction, target_id: str) -> None:
    record = PendingRecord(
        id="pending-s",
        memory_type=MemoryType.SEMANTIC,
        content="Works at Google",
        memory_data={"content": "Works at Google"},
        created_at=datetime.now(UTC),
        status="pending",
        resolution_action=action,
        target_memory_id=target_id,
        target_content="Works at Acme",
    )
    mock_relational_store.get_pending.side_effect = lambda _pid: record


class TestApprovalScope:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("action", _ACTIONS)
    async def test_target_outside_the_reviewer_namespaces_is_refused(
        self, action, docs, make_manager, mock_relational_store
    ):
        """An agent limited to its own scope writes memories the default reviewer cannot read."""
        private_agent = make_manager(
            agent_id="agent-x",
            memory_policy=AgentMemoryPolicy(agent_id="agent-x", read_scopes=(MemoryScopeLevel.AGENT,)),
        )
        await private_agent.store(SemanticMemory(content="Works at Acme"))
        target_id, stored_doc = next(iter(docs.items()))
        assert stored_doc.metadata["namespaces"] == ["agent:agent-x"]
        _queue(mock_relational_store, action, target_id)

        with pytest.raises(PendingTargetChangedError):
            await make_manager().approve("pending-s")

        assert list(docs) == [target_id]
        assert not docs[target_id].metadata.get("corrected")
        assert not docs[target_id].metadata.get("archived")
        mock_relational_store.mark_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_target_shared_through_global_is_corrected_by_the_default_reviewer(
        self, docs, make_manager, mock_relational_store
    ):
        await make_manager(agent_id="agent-x").store(SemanticMemory(content="Works at Acme"))
        target_id = next(iter(docs))
        _queue(mock_relational_store, PendingResolutionAction.CORRECT, target_id)

        corrected = await make_manager().approve("pending-s")

        assert corrected is not None and corrected.content == "Works at Google"
        assert docs[target_id].metadata["corrected"] is True
        mock_relational_store.mark_pending.assert_called_once_with("pending-s", "approved")

    @pytest.mark.asyncio
    async def test_target_shared_through_global_is_archived_by_the_default_reviewer(
        self, docs, make_manager, mock_relational_store
    ):
        await make_manager(agent_id="agent-x").store(SemanticMemory(content="Works at Acme"))
        target_id = next(iter(docs))
        _queue(mock_relational_store, PendingResolutionAction.DELETE, target_id)

        await make_manager().approve("pending-s")

        assert docs[target_id].metadata["archived"] is True
        mock_relational_store.mark_pending.assert_called_once_with("pending-s", "approved")

    @pytest.mark.asyncio
    async def test_target_that_is_gone_keeps_the_existing_resolution(self, docs, make_manager, mock_relational_store):
        """A purged target is not an out-of-scope one: a correction is kept as a new memory."""
        _queue(mock_relational_store, PendingResolutionAction.CORRECT, "mem-purged")

        stored = await make_manager().approve("pending-s")

        assert stored is not None and stored.content == "Works at Google"
        assert len(docs) == 1
        mock_relational_store.mark_pending.assert_called_once_with("pending-s", "approved")

    @pytest.mark.asyncio
    async def test_forgetting_a_target_that_is_gone_still_approves_as_a_noop(
        self, docs, make_manager, mock_relational_store
    ):
        _queue(mock_relational_store, PendingResolutionAction.DELETE, "mem-purged")

        assert await make_manager().approve("pending-s") is None

        assert docs == {}
        mock_relational_store.mark_pending.assert_called_once_with("pending-s", "approved")


class TestSnapshotContract:
    """The stale-target guard compares a recall snapshot with a later read; both must see the same text."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "content",
        ["Works at Acme", "  padded \n multi-line\ttext  ", "中文 \u00e9\u00e8 mixed ✓", "x" * 5000],
        ids=["plain", "whitespace", "unicode", "long"],
    )
    async def test_search_and_get_return_identical_content(self, content, mock_vector_store, memory_config):
        doc = semantic_to_doc(SemanticMemory(id="mem-1", content=content, embedding=[0.1] * 768))
        doc.metadata["namespaces"] = ["global"]

        async def _get(_collection, ids):
            return [doc for i in ids if i == doc.id]

        mock_vector_store.get.side_effect = _get
        mock_vector_store.search.return_value = [SimpleNamespace(document=doc, score=0.9)]

        searched = await search_semantic([0.1] * 768, 5, mock_vector_store, memory_config, namespaces=["global"])
        fetched = await get_from_vector("mem-1", mock_vector_store, memory_config, namespaces=["global"])

        assert fetched is not None
        assert [r.memory.content for r in searched] == [fetched.content] == [content]
