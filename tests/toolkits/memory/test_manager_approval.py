"""Tests for MemoryManager approval workflow."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryNotFoundError
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    MemoryStatus,
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
    SemanticMemory,
)


class TestApprovalWorkflow:
    """Test approval-related methods."""

    @pytest.fixture(autouse=True)
    def mock_scan(self):
        with patch("myrm_agent_harness.toolkits.memory._internal.write_service.scan_and_clean_memory") as mock:
            mock.return_value = None
            yield mock

    @pytest.mark.asyncio
    async def test_submit_pending_new_memory(self, mock_relational_store, memory_config):
        """Test submitting a new memory for approval."""
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        memory = SemanticMemory(content="New fact to approve")
        pending_id = await manager.submit_pending(memory)

        assert pending_id == "pending-1"
        mock_relational_store.pending_exists.assert_called_once()
        mock_relational_store.submit_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_pending_duplicate_returns_empty(self, mock_relational_store, memory_config):
        """Test submitting duplicate pending memory returns empty string."""
        mock_relational_store.pending_exists.return_value = True

        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        memory = SemanticMemory(content="Duplicate fact")
        pending_id = await manager.submit_pending(memory)

        assert pending_id == ""
        mock_relational_store.submit_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_semantic_memory(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test approving a semantic memory."""
        pending_record = PendingRecord(
            id="pending-1",
            memory_type=MemoryType.SEMANTIC,
            content="Approved fact",
            memory_data={"content": "Approved fact", "importance": 0.8},
            created_at=datetime.now(UTC),
            status="pending",
        )
        mock_relational_store.get_pending.return_value = pending_record
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        result = await manager.approve("pending-1")

        assert result is not None
        assert isinstance(result, SemanticMemory)
        mock_relational_store.mark_pending.assert_called_once_with("pending-1", "approved")

    @pytest.mark.asyncio
    async def test_approve_profile_memory(self, mock_relational_store, memory_config):
        """Test approving a profile memory (key-value)."""
        pending_record = PendingRecord(
            id="pending-1",
            memory_type=MemoryType.PROFILE,
            content="timezone: UTC+8",
            memory_data={"key": "timezone", "value": "UTC+8"},
            created_at=datetime.now(UTC),
            status="pending",
        )
        mock_relational_store.get_pending.return_value = pending_record

        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        result = await manager.approve("pending-1")

        assert result is None
        call_args = mock_relational_store.set_profile.call_args
        assert call_args[0][:2] == ("timezone", "UTC+8")
        mock_relational_store.mark_pending.assert_called_once_with("pending-1", "approved")

    @pytest.mark.asyncio
    async def test_approve_not_found_raises_error(self, mock_relational_store, memory_config):
        """Test approving non-existent pending memory raises error."""
        mock_relational_store.get_pending.return_value = None

        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with pytest.raises(MemoryNotFoundError, match="Pending record pending-1 not found"):
            await manager.approve("pending-1")

    @pytest.mark.asyncio
    @staticmethod
    def _forget_record() -> PendingRecord:
        return PendingRecord(
            id="pending-del",
            memory_type=MemoryType.SEMANTIC,
            content="Remove stale fact",
            memory_data={"content": "Remove stale fact", "importance": 0.5},
            created_at=datetime.now(UTC),
            status="pending",
            resolution_action=PendingResolutionAction.DELETE,
            target_memory_id="mem-stale",
        )

    @pytest.mark.asyncio
    async def test_approve_delete_action_archives_target(self, mock_relational_store, memory_config):
        """Approving a DELETE proposal archives (not hard-deletes) the target memory."""
        mock_relational_store.get_pending.return_value = self._forget_record()
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with (
            patch.object(manager, "update_memory", return_value=SemanticMemory(content="x")) as update,
            patch.object(manager, "delete_memory_by_id") as hard_delete,
        ):
            result = await manager.approve("pending-del")

        assert result is None
        update.assert_awaited_once_with("mem-stale", status=MemoryStatus.ARCHIVED)
        hard_delete.assert_not_called()
        mock_relational_store.mark_pending.assert_called_once_with("pending-del", "approved")

    @pytest.mark.asyncio
    async def test_approve_delete_action_is_idempotent_when_target_gone(self, mock_relational_store, memory_config):
        """A forget target already purged still resolves the proposal instead of failing."""
        mock_relational_store.get_pending.return_value = self._forget_record()
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with patch.object(manager, "update_memory", side_effect=MemoryNotFoundError("gone")):
            result = await manager.approve("pending-del")

        assert result is None
        mock_relational_store.mark_pending.assert_called_once_with("pending-del", "approved")

    @pytest.mark.asyncio
    async def test_approve_rejects_edit_on_delete_action(self, mock_relational_store, memory_config):
        """A forget proposal persists no text, so an edit must fail loudly and leave it pending."""
        mock_relational_store.get_pending.return_value = self._forget_record()
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with patch.object(manager, "update_memory") as update, pytest.raises(ValueError, match="no editable content"):
            await manager.approve("pending-del", edited_content="reworded")

        update.assert_not_called()
        mock_relational_store.mark_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_store_persists_edited_content(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """The reviewer's rewording is what gets stored, not the original proposal."""
        mock_relational_store.get_pending.return_value = PendingRecord(
            id="pending-1",
            memory_type=MemoryType.SEMANTIC,
            content="Original wording",
            memory_data={"content": "Original wording", "importance": 0.8},
            created_at=datetime.now(UTC),
            status="pending",
        )
        mock_vector_store.upsert.return_value = ["mem-1"]
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        result = await manager.approve("pending-1", edited_content="  Edited wording  ")

        assert isinstance(result, SemanticMemory)
        assert result.content == "Edited wording"
        mock_relational_store.mark_pending.assert_called_once_with("pending-1", "approved")

    @pytest.mark.asyncio
    async def test_approve_correct_action_applies_edited_content(self, mock_relational_store, memory_config):
        """CORRECT reads ``record.content``; the edit must reach it, not only ``memory_data``."""
        mock_relational_store.get_pending.return_value = PendingRecord(
            id="pending-fix",
            memory_type=MemoryType.SEMANTIC,
            content="Original wording",
            memory_data={"content": "Original wording"},
            created_at=datetime.now(UTC),
            status="pending",
            resolution_action=PendingResolutionAction.CORRECT,
            target_memory_id="mem-old",
        )
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with patch.object(manager, "correct_memory", return_value=SemanticMemory(content="x")) as correct:
            await manager.approve("pending-fix", edited_content="Edited wording")

        correct.assert_awaited_once_with("mem-old", "Edited wording")

    @pytest.mark.asyncio
    async def test_approve_rejects_blank_edit_and_profile_edit(self, mock_relational_store, memory_config):
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )
        mock_relational_store.get_pending.return_value = PendingRecord(
            id="pending-1",
            memory_type=MemoryType.SEMANTIC,
            content="Fact",
            memory_data={"content": "Fact"},
            created_at=datetime.now(UTC),
            status="pending",
        )
        with pytest.raises(ValueError, match="must not be empty"):
            await manager.approve("pending-1", edited_content="   ")

        mock_relational_store.get_pending.return_value = PendingRecord(
            id="pending-2",
            memory_type=MemoryType.PROFILE,
            content="timezone: UTC+8",
            memory_data={"key": "timezone", "value": "UTC+8"},
            created_at=datetime.now(UTC),
            status="pending",
        )
        with pytest.raises(ValueError, match="no editable content"):
            await manager.approve("pending-2", edited_content="timezone: UTC+9")

        mock_relational_store.set_profile.assert_not_called()
        mock_relational_store.mark_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_correct_action_delegates_to_correct_memory(self, mock_relational_store, memory_config):
        """Approving a CORRECT proposal demotes the target and stores the corrected fact."""
        pending_record = PendingRecord(
            id="pending-fix",
            memory_type=MemoryType.SEMANTIC,
            content="User now works at Google",
            memory_data={"content": "User now works at Google", "importance": 0.8},
            created_at=datetime.now(UTC),
            status="pending",
            resolution_action=PendingResolutionAction.CORRECT,
            target_memory_id="mem-old",
        )
        mock_relational_store.get_pending.return_value = pending_record

        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )
        corrected = SemanticMemory(content="User now works at Google")
        correct_calls: list[tuple[str, str]] = []

        async def _record_correct(memory_id: str, content: str) -> SemanticMemory:
            correct_calls.append((memory_id, content))
            return corrected

        with patch.object(manager, "correct_memory", side_effect=_record_correct):
            result = await manager.approve("pending-fix")

        assert result is corrected
        assert correct_calls == [("mem-old", "User now works at Google")]
        mock_relational_store.mark_pending.assert_called_once_with("pending-fix", "approved")

    @pytest.mark.asyncio
    async def test_approve_correct_action_degrades_to_store_when_target_gone(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """When the correction target was forgotten/purged, approval stores the correction instead of 500."""
        pending_record = PendingRecord(
            id="pending-fix",
            memory_type=MemoryType.SEMANTIC,
            content="User now works at Google",
            memory_data={"content": "User now works at Google", "importance": 0.8},
            created_at=datetime.now(UTC),
            status="pending",
            resolution_action=PendingResolutionAction.CORRECT,
            target_memory_id="mem-vanished",
        )
        mock_relational_store.get_pending.return_value = pending_record
        mock_vector_store.upsert.return_value = ["mem-new"]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        with patch.object(
            manager,
            "correct_memory",
            side_effect=MemoryNotFoundError("Memory mem-vanished not found"),
        ):
            result = await manager.approve("pending-fix")

        # The confirmed fact must be persisted as a new memory, and the pending row resolved.
        assert isinstance(result, SemanticMemory)
        mock_vector_store.upsert.assert_called()
        mock_relational_store.mark_pending.assert_called_once_with("pending-fix", "approved")

    @pytest.mark.asyncio
    async def test_reject_pending_memory(self, mock_relational_store, memory_config):
        """Test rejecting a pending memory."""
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        await manager.reject("pending-1")

        mock_relational_store.mark_pending.assert_called_once_with("pending-1", "rejected")

    @pytest.mark.asyncio
    async def test_list_pending(self, mock_relational_store, memory_config):
        """Test listing pending memories."""
        pending_list = [
            PendingRecord(
                id="p1",
                memory_type=MemoryType.SEMANTIC,
                content="Test pending memory",
                memory_data={},
                created_at=datetime.now(UTC),
                status="pending",
            )
        ]
        mock_relational_store.list_pending.return_value = pending_list

        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        result = await manager.list_pending(limit=50)

        assert result == pending_list
        mock_relational_store.list_pending.assert_called_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_count_pending(self, mock_relational_store, memory_config):
        """Test counting pending memories."""
        mock_relational_store.count_pending.return_value = 5

        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        count = await manager.count_pending()

        assert count == 5
        mock_relational_store.count_pending.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_batch_approve_all_success(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test batch approval with all successes."""
        pending_record = PendingRecord(
            id="pending-1",
            memory_type=MemoryType.SEMANTIC,
            content="Test content",
            memory_data={"content": "Test", "importance": 0.5},
            created_at=datetime.now(UTC),
            status="pending",
        )
        mock_relational_store.get_pending.return_value = pending_record
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        success, failed = await manager.batch_approve(["pending-1", "pending-2", "pending-3"])

        assert success == 3
        assert failed == []

    @pytest.mark.asyncio
    async def test_batch_approve_partial_failure(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Test batch approval with some failures."""

        async def mock_get_pending(pending_id: str):
            if pending_id == "pending-fail":
                return None
            return PendingRecord(
                id=pending_id,
                memory_type=MemoryType.SEMANTIC,
                content="Test content",
                memory_data={"content": "Test", "importance": 0.5},
                created_at=datetime.now(UTC),
                status="pending",
            )

        mock_relational_store.get_pending.side_effect = mock_get_pending
        mock_vector_store.upsert.return_value = ["mem-1"]

        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        success, failed = await manager.batch_approve(["pending-1", "pending-fail", "pending-3"])

        assert success == 2
        assert "pending-fail" in failed
        assert len(failed) == 1

    @pytest.mark.asyncio
    async def test_batch_reject(self, mock_relational_store, memory_config):
        """Test batch rejection of pending memories."""
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        count = await manager.batch_reject(["p1", "p2", "p3"])

        assert count == 3
        mock_relational_store.batch_mark_pending.assert_called_once_with(["p1", "p2", "p3"], "rejected")

    @pytest.mark.asyncio
    async def test_store_batch_force_pending_without_approval_flag(self, mock_relational_store, memory_config):
        """Inferred writes must queue pending even when approval_required=False."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            relational=mock_relational_store,
            approval_required=False,
        )

        memory = SemanticMemory(content="Inferred fact from auto-extraction")
        stored = await manager.store_batch([memory], _force_pending=True)

        assert len(stored) == 1
        assert stored[0].metadata.get("write_intent") == "inferred"
        mock_relational_store.submit_pending.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_knowledge_bypasses_approval_gate(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """Explicit memory_save_tool path writes directly."""
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        result = await manager.add_knowledge("User asked me to remember this")

        assert isinstance(result, SemanticMemory)
        mock_relational_store.submit_pending.assert_not_called()
        mock_vector_store.upsert.assert_called()
