"""Tests for ephemeral.py: ReadOnlyMemoryView and EphemeralMemoryManager.

Covers:
- ReadOnlyMemoryView: all 28 write/mutate methods raise PermissionError
- ReadOnlyMemoryView: all read methods delegate to parent
- ReadOnlyMemoryView: property delegation
- EphemeralMemoryManager: ephemeral store + parent read delegation
- EphemeralMemoryManager: search combines parent + ephemeral results
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)


def _make_parent_mock() -> MagicMock:
    parent = MagicMock()
    parent._namespaces = ["ns-1"]
    parent._scope = MagicMock()
    parent._config = MagicMock()
    type(parent).has_relational = PropertyMock(return_value=True)
    type(parent).has_vector = PropertyMock(return_value=True)
    type(parent).has_graph = PropertyMock(return_value=False)
    parent.search = AsyncMock(return_value=[])
    parent.get_context = AsyncMock(return_value={"key": "value"})
    parent.get_learned_context = AsyncMock(return_value={"rules": [{"k": "v"}]})
    parent.get_memory = AsyncMock(return_value=None)
    parent.begin_session = MagicMock(return_value="session-ctx")
    parent.end_session = AsyncMock(return_value=[])
    return parent


class TestReadOnlyMemoryViewWriteDenied:
    """All write/mutate methods must raise PermissionError."""

    def _make_view(self):
        from myrm_agent_harness.toolkits.memory.ephemeral import ReadOnlyMemoryView

        return ReadOnlyMemoryView(_make_parent_mock())

    @pytest.mark.asyncio
    async def test_store_denied(self):
        view = self._make_view()
        mem = SemanticMemory(content="test")
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.store(mem)

    @pytest.mark.asyncio
    async def test_store_batch_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.store_batch([SemanticMemory(content="a")])

    @pytest.mark.asyncio
    async def test_add_knowledge_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.add_knowledge("some knowledge")

    @pytest.mark.asyncio
    async def test_add_event_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.add_event("some event")

    @pytest.mark.asyncio
    async def test_add_rule_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.add_rule("trigger", "action")

    @pytest.mark.asyncio
    async def test_delete_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.delete_memory("collection", ["id-1"])

    @pytest.mark.asyncio
    async def test_delete_rule_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.delete_rule("rule-1")

    @pytest.mark.asyncio
    async def test_delete_all_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.delete_all()

    @pytest.mark.asyncio
    async def test_delete_by_type_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.delete_by_type(MemoryType.SEMANTIC)

    @pytest.mark.asyncio
    async def test_delete_profile_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.delete_profile("key-1")

    @pytest.mark.asyncio
    async def test_correct_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.correct_memory("mem-1", "corrected")

    @pytest.mark.asyncio
    async def test_archive_memories_auto_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.archive_memories_auto()

    @pytest.mark.asyncio
    async def test_restore_backup_denied(self):
        view = self._make_view()
        strategy = MagicMock()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.restore_backup("backup-1", strategy)

    @pytest.mark.asyncio
    async def test_delete_backup_denied(self):
        view = self._make_view()
        strategy = MagicMock()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.delete_backup("backup-1", strategy)

    @pytest.mark.asyncio
    async def test_run_maintenance_cycle_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.run_maintenance_cycle()

    @pytest.mark.asyncio
    async def test_set_profile_attribute_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.set_profile_attribute("key", "value")

    @pytest.mark.asyncio
    async def test_approve_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.approve("pending-1")

    @pytest.mark.asyncio
    async def test_reject_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.reject("pending-1")

    @pytest.mark.asyncio
    async def test_batch_approve_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.batch_approve(["p-1", "p-2"])

    @pytest.mark.asyncio
    async def test_batch_reject_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.batch_reject(["p-1", "p-2"])

    @pytest.mark.asyncio
    async def test_rate_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.rate_memory("mem-1", 5)

    @pytest.mark.asyncio
    async def test_pin_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.pin_memory("mem-1")

    @pytest.mark.asyncio
    async def test_unpin_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.unpin_memory("mem-1")

    @pytest.mark.asyncio
    async def test_update_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.update_memory("mem-1", content="new content")

    @pytest.mark.asyncio
    async def test_unarchive_memory_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.unarchive_memory("mem-1")

    @pytest.mark.asyncio
    async def test_create_backup_denied(self):
        view = self._make_view()
        strategy = MagicMock()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.create_backup(strategy)

    @pytest.mark.asyncio
    async def test_import_memories_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.import_memories({"semantic": [{"content": "test"}]})

    @pytest.mark.asyncio
    async def test_submit_pending_denied(self):
        view = self._make_view()
        mem = SemanticMemory(content="pending")
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.submit_pending(mem)

    @pytest.mark.asyncio
    async def test_unarchive_memories_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            await view.unarchive_memories(["id-1"], MemoryType.SEMANTIC)

    def test_set_last_cited_memory_ids_denied(self):
        view = self._make_view()
        with pytest.raises(PermissionError, match="READ_ONLY_GLOBAL"):
            view.set_last_cited_memory_ids(["id-1"])


class TestReadOnlyMemoryViewReadDelegation:
    """Read operations must delegate to parent."""

    def _make_view(self):
        from myrm_agent_harness.toolkits.memory.ephemeral import ReadOnlyMemoryView

        parent = _make_parent_mock()
        return ReadOnlyMemoryView(parent), parent

    @pytest.mark.asyncio
    async def test_search_delegates(self):
        view, parent = self._make_view()
        await view.search("query")
        parent.search.assert_awaited_once_with("query", memory_types=None, limit=10)

    @pytest.mark.asyncio
    async def test_get_context_delegates(self):
        view, parent = self._make_view()
        result = await view.get_context()
        parent.get_context.assert_awaited_once()
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_get_learned_context_delegates(self):
        view, parent = self._make_view()
        result = await view.get_learned_context()
        parent.get_learned_context.assert_awaited_once()
        assert "rules" in result

    @pytest.mark.asyncio
    async def test_get_memory_delegates(self):
        view, parent = self._make_view()
        await view.get_memory("mem-1")
        parent.get_memory.assert_awaited_once_with("mem-1")

    def test_begin_session_delegates(self):
        view, parent = self._make_view()
        result = view.begin_session("chat-1")
        parent.begin_session.assert_called_once_with("chat-1", hook_registry=None)
        assert result == "session-ctx"

    @pytest.mark.asyncio
    async def test_end_session_returns_empty(self):
        view, _parent = self._make_view()
        result = await view.end_session()
        assert result == []

    @pytest.mark.asyncio
    async def test_close_is_noop(self):
        view, _parent = self._make_view()
        await view.close()

    @pytest.mark.asyncio
    async def test_list_pending_returns_empty(self):
        view, _parent = self._make_view()
        result = await view.list_pending()
        assert result == []

    @pytest.mark.asyncio
    async def test_count_pending_returns_zero(self):
        view, _parent = self._make_view()
        result = await view.count_pending()
        assert result == 0

    @pytest.mark.asyncio
    async def test_search_archived_returns_empty(self):
        view, _parent = self._make_view()
        result = await view.search_archived("query", MemoryType.SEMANTIC)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_memories_delegates(self):
        view, parent = self._make_view()
        parent.list_memories = AsyncMock(return_value=[])
        result = await view.list_memories(MemoryType.SEMANTIC)
        parent.list_memories.assert_awaited_once()
        assert result == []

    @pytest.mark.asyncio
    async def test_count_memories_delegates(self):
        view, parent = self._make_view()
        parent.count_memories = AsyncMock(return_value=42)
        result = await view.count_memories(MemoryType.SEMANTIC)
        assert result == 42

    @pytest.mark.asyncio
    async def test_export_all_delegates(self):
        view, parent = self._make_view()
        parent.export_all = AsyncMock(return_value={"semantic": []})
        result = await view.export_all()
        assert "semantic" in result

    def test_get_enabled_types_delegates(self):
        view, parent = self._make_view()
        parent.get_enabled_types = MagicMock(return_value=[MemoryType.SEMANTIC])
        result = view.get_enabled_types()
        assert MemoryType.SEMANTIC in result

    @pytest.mark.asyncio
    async def test_compute_health_score_delegates(self):
        view, parent = self._make_view()
        mock_score = MagicMock()
        parent.compute_health_score = AsyncMock(return_value=mock_score)
        result = await view.compute_health_score()
        assert result is mock_score

    def test_properties(self):
        view, _parent = self._make_view()
        assert view.namespaces == ["ns-1"]
        assert view.has_relational is True
        assert view.has_vector is True
        assert view.has_graph is False

    def test_inherited_properties_no_attribute_error(self):
        """All inherited properties must be accessible without AttributeError."""
        view, _ = self._make_view()
        assert view.active_session is None
        assert view.approval_required is False
        assert view.config is not None
        assert view.last_cited_memory_ids == []
        assert view.scope is not None


class TestEphemeralMemoryManager:
    """EphemeralMemoryManager stores locally, reads from parent."""

    def _make_ephemeral(self):
        from myrm_agent_harness.toolkits.memory.ephemeral import EphemeralMemoryManager

        parent = _make_parent_mock()
        return EphemeralMemoryManager(parent), parent

    @pytest.mark.asyncio
    async def test_store_goes_to_ephemeral(self):
        eph, _parent = self._make_ephemeral()
        mem = SemanticMemory(content="ephemeral data")
        stored = await eph.store(mem)
        assert stored.id is not None
        assert stored.content == "ephemeral data"

    @pytest.mark.asyncio
    async def test_store_batch(self):
        eph, _parent = self._make_ephemeral()
        mems = [SemanticMemory(content="a"), SemanticMemory(content="b")]
        results = await eph.store_batch(mems)
        assert len(results) == 2
        assert all(m.id for m in results)

    @pytest.mark.asyncio
    async def test_get_memory_from_ephemeral(self):
        eph, _parent = self._make_ephemeral()
        mem = SemanticMemory(content="local")
        stored = await eph.store(mem)
        found = await eph.get_memory(stored.id)
        assert found is not None
        assert found.content == "local"

    @pytest.mark.asyncio
    async def test_get_memory_falls_back_to_parent(self):
        eph, parent = self._make_ephemeral()
        parent.get_memory = AsyncMock(return_value=SemanticMemory(content="from parent"))
        found = await eph.get_memory("nonexistent-id")
        parent.get_memory.assert_awaited_once_with("nonexistent-id")
        assert found.content == "from parent"

    @pytest.mark.asyncio
    async def test_search_combines_results(self):
        eph, parent = self._make_ephemeral()
        parent_mem = SemanticMemory(content="parent data about cats")
        parent.search = AsyncMock(
            return_value=[MemorySearchResult(memory=parent_mem, score=0.8, memory_type=MemoryType.SEMANTIC)]
        )
        await eph.add_knowledge("cats are wonderful")
        results = await eph.search("cats")
        assert len(results) == 2
        assert results[0].score >= results[1].score

    @pytest.mark.asyncio
    async def test_add_knowledge(self):
        eph, _parent = self._make_ephemeral()
        mem = await eph.add_knowledge("test knowledge", importance=0.9, tags=["tag1"])
        assert isinstance(mem, SemanticMemory)
        assert mem.content == "test knowledge"
        assert mem.importance == 0.9

    @pytest.mark.asyncio
    async def test_add_event(self):
        eph, _parent = self._make_ephemeral()
        mem = await eph.add_event("test event", event_type="action")
        assert isinstance(mem, EpisodicMemory)
        assert mem.content == "test event"

    @pytest.mark.asyncio
    async def test_add_rule(self):
        eph, _parent = self._make_ephemeral()
        mem = await eph.add_rule("when X", "do Y", priority=5)
        assert isinstance(mem, ProceduralMemory)
        assert mem.trigger == "when X"
        assert mem.action == "do Y"
        assert mem.content is not None

    @pytest.mark.asyncio
    async def test_get_context_delegates_to_parent(self):
        eph, parent = self._make_ephemeral()
        await eph.get_context()
        parent.get_context.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_learned_context_delegates(self):
        eph, parent = self._make_ephemeral()
        await eph.get_learned_context()
        parent.get_learned_context.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_store_assigns_id_when_missing(self):
        """Memory without id gets a UUID assigned."""
        eph, _ = self._make_ephemeral()
        mem = SemanticMemory(content="no-id")
        mem.id = ""
        stored = await eph.store(mem)
        assert stored.id != ""
        assert len(stored.id) == 36  # UUID format

    @pytest.mark.asyncio
    async def test_search_filters_by_memory_type(self):
        """Ephemeral search respects memory_types filter."""
        eph, parent = self._make_ephemeral()
        parent.search = AsyncMock(return_value=[])
        await eph.add_knowledge("semantic content")
        await eph.add_event("episodic content about semantic content")

        results = await eph.search("content", memory_types=[MemoryType.SEMANTIC])
        assert all(r.memory_type == MemoryType.SEMANTIC for r in results)

    @pytest.mark.asyncio
    async def test_search_no_match_in_ephemeral(self):
        """Search returns only parent results when no ephemeral match."""
        eph, parent = self._make_ephemeral()
        parent_mem = SemanticMemory(content="xyz")
        parent.search = AsyncMock(
            return_value=[MemorySearchResult(memory=parent_mem, score=0.5, memory_type=MemoryType.SEMANTIC)]
        )
        await eph.add_knowledge("unrelated data")
        results = await eph.search("xyz")
        assert len(results) == 1
        assert results[0].memory.content == "xyz"

    @pytest.mark.asyncio
    async def test_search_respects_limit(self):
        """Combined results are trimmed to limit."""
        eph, parent = self._make_ephemeral()
        parent.search = AsyncMock(return_value=[])
        for i in range(5):
            await eph.add_knowledge(f"item {i} about cats")
        results = await eph.search("cats", limit=3)
        assert len(results) == 3

    def test_begin_session_delegates(self):
        eph, parent = self._make_ephemeral()
        result = eph.begin_session("chat-99")
        parent.begin_session.assert_called_once_with("chat-99", hook_registry=None)
        assert result == "session-ctx"

    @pytest.mark.asyncio
    async def test_end_session_delegates(self):
        eph, parent = self._make_ephemeral()
        await eph.end_session()
        parent.end_session.assert_awaited_once()

    def test_properties(self):
        eph, _parent = self._make_ephemeral()
        assert eph.namespaces == ["ns-1"]
        assert eph.has_relational is True
        assert eph.has_vector is True
        assert eph.has_graph is False

    def test_inherited_properties_no_attribute_error(self):
        """All inherited properties must be accessible without AttributeError."""
        eph, _ = self._make_ephemeral()
        assert eph.active_session is None
        assert eph.approval_required is False
        assert eph.config is not None
        assert eph.last_cited_memory_ids == []
        assert eph.scope is not None

    @pytest.mark.asyncio
    async def test_close_clears_ephemeral_store(self):
        eph, _ = self._make_ephemeral()
        await eph.add_knowledge("temp data")
        assert len(eph._ephemeral_store) > 0
        await eph.close()
        assert len(eph._ephemeral_store) == 0

    @pytest.mark.asyncio
    async def test_set_profile_attribute_stores_locally(self):
        eph, _ = self._make_ephemeral()
        result = await eph.set_profile_attribute("name", "Alice")
        assert result is None
        assert len(eph._ephemeral_store) == 1

    def test_set_last_cited_memory_ids(self):
        eph, _ = self._make_ephemeral()
        eph.set_last_cited_memory_ids(["id-1", "id-2"])
        assert eph.last_cited_memory_ids == ["id-1", "id-2"]

    @pytest.mark.asyncio
    async def test_rate_memory_ephemeral(self):
        eph, _parent = self._make_ephemeral()
        mem = await eph.add_knowledge("test")
        result = await eph.rate_memory(mem.id, 5)
        assert result is True

    @pytest.mark.asyncio
    async def test_rate_memory_delegates_to_parent(self):
        eph, parent = self._make_ephemeral()
        parent.rate_memory = AsyncMock(return_value=True)
        await eph.rate_memory("nonexistent", 3)
        parent.rate_memory.assert_awaited_once_with("nonexistent", 3, None)

    @pytest.mark.asyncio
    async def test_delete_memory_from_ephemeral(self):
        eph, _ = self._make_ephemeral()
        mem = await eph.add_knowledge("to delete")
        result = await eph.delete_memory("any", [mem.id])
        assert result == 1
        assert mem.id not in eph._ephemeral_store

    @pytest.mark.asyncio
    async def test_get_profile_attribute_delegates(self):
        eph, parent = self._make_ephemeral()
        parent.get_profile_attribute = AsyncMock(return_value="value")
        result = await eph.get_profile_attribute("key")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_list_memories_delegates(self):
        eph, parent = self._make_ephemeral()
        parent.list_memories = AsyncMock(return_value=[])
        await eph.list_memories(MemoryType.SEMANTIC)
        parent.list_memories.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_count_memories_delegates(self):
        eph, parent = self._make_ephemeral()
        parent.count_memories = AsyncMock(return_value=10)
        result = await eph.count_memories(MemoryType.SEMANTIC)
        assert result == 10

    def test_get_enabled_types_delegates(self):
        eph, parent = self._make_ephemeral()
        parent.get_enabled_types = MagicMock(return_value=[MemoryType.SEMANTIC])
        result = eph.get_enabled_types()
        assert MemoryType.SEMANTIC in result
