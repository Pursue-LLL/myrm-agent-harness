"""Approval dispatches on ``resolution_action``: STORE, CORRECT (with fallback) and DELETE, plus reviewer edits."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import InvalidPendingEditError, MemoryNotFoundError
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    MemoryStatus,
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
    SemanticMemory,
)


class TestPendingResolutionActions:
    @pytest.fixture(autouse=True)
    def mock_scan(self):
        with patch("myrm_agent_harness.toolkits.memory._internal.write_service.scan_and_clean_memory") as mock:
            mock.return_value = None
            yield mock

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

        with (
            patch.object(manager, "update_memory") as update,
            pytest.raises(InvalidPendingEditError, match="no editable content"),
        ):
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
        with pytest.raises(InvalidPendingEditError, match="must not be empty"):
            await manager.approve("pending-1", edited_content="   ")

        mock_relational_store.get_pending.return_value = PendingRecord(
            id="pending-2",
            memory_type=MemoryType.PROFILE,
            content="timezone: UTC+8",
            memory_data={"key": "timezone", "value": "UTC+8"},
            created_at=datetime.now(UTC),
            status="pending",
        )
        with pytest.raises(InvalidPendingEditError, match="no editable content"):
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
