"""Approval of CORRECT/DELETE proposals refuses a target that changed after the proposal was queued."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import PendingTargetChangedError
from myrm_agent_harness.toolkits.memory._internal.storage_converters import semantic_to_doc
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    MemoryStatus,
    MemoryType,
    PendingRecord,
    PendingResolutionAction,
    SemanticMemory,
)


class TestPendingTargetGuard:
    @pytest.fixture(autouse=True)
    def mock_scan(self):
        with patch("myrm_agent_harness.toolkits.memory._internal.write_service.scan_and_clean_memory") as mock:
            mock.return_value = None
            yield mock

    @staticmethod
    def _target_record(action: PendingResolutionAction, shown: str | None = "Works at Acme") -> PendingRecord:
        return PendingRecord(
            id="pending-t",
            memory_type=MemoryType.SEMANTIC,
            content="Works at Google",
            memory_data={"content": "Works at Google"},
            created_at=datetime.now(UTC),
            status="pending",
            resolution_action=action,
            target_memory_id="mem-old",
            target_content=shown,
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "target",
        [
            SemanticMemory(content="Works at Initech"),
            SemanticMemory(content="Works at Acme", metadata={"corrected": True}),
            SemanticMemory(content="Works at Acme", status=MemoryStatus.ARCHIVED),
        ],
        ids=["edited", "already-corrected", "not-active"],
    )
    async def test_approve_correct_refuses_changed_target(self, mock_relational_store, memory_config, target):
        """A second correction (or one over a hand-edited fact) must not silently apply."""
        mock_relational_store.get_pending.return_value = self._target_record(PendingResolutionAction.CORRECT)
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with (
            patch.object(manager, "get_memory", return_value=target),
            patch.object(manager, "correct_memory") as correct,
            pytest.raises(PendingTargetChangedError, match="review it again"),
        ):
            await manager.approve("pending-t")

        correct.assert_not_called()
        mock_relational_store.mark_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_refusal_logs_why_the_target_drifted(self, mock_relational_store, memory_config, caplog):
        """The reason is the only signal for telling genuine drift from a snapshot that no longer matches reads."""
        mock_relational_store.get_pending.return_value = self._target_record(PendingResolutionAction.CORRECT)
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )
        target = SemanticMemory(content="Works at Acme", metadata={"corrected": True})

        with (
            caplog.at_level("INFO"),
            patch.object(manager, "get_memory", return_value=target),
            pytest.raises(PendingTargetChangedError),
        ):
            await manager.approve("pending-t")

        assert "already_corrected" in caplog.text

    @pytest.mark.asyncio
    async def test_approve_correct_applies_when_target_unchanged(self, mock_relational_store, memory_config):
        mock_relational_store.get_pending.return_value = self._target_record(PendingResolutionAction.CORRECT)
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with (
            patch.object(manager, "get_memory", return_value=SemanticMemory(content="Works at Acme")),
            patch.object(manager, "correct_memory", return_value=SemanticMemory(content="x")) as correct,
        ):
            await manager.approve("pending-t")

        correct.assert_awaited_once_with("mem-old", "Works at Google")
        mock_relational_store.mark_pending.assert_called_once_with("pending-t", "approved")

    @pytest.mark.asyncio
    async def test_approve_correct_without_snapshot_skips_content_check(self, mock_relational_store, memory_config):
        """Legacy rows carry no snapshot; only liveness/corrected state can be verified."""
        mock_relational_store.get_pending.return_value = self._target_record(PendingResolutionAction.CORRECT, None)
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with (
            patch.object(manager, "get_memory", return_value=SemanticMemory(content="anything")),
            patch.object(manager, "correct_memory", return_value=SemanticMemory(content="x")) as correct,
        ):
            await manager.approve("pending-t")

        correct.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_approve_delete_refuses_edited_target(self, mock_relational_store, memory_config):
        """Archiving a fact the user has since rewritten would erase their edit."""
        mock_relational_store.get_pending.return_value = self._target_record(PendingResolutionAction.DELETE)
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        with (
            patch.object(manager, "get_memory", return_value=SemanticMemory(content="Works at Initech")),
            patch.object(manager, "update_memory") as update,
            pytest.raises(PendingTargetChangedError),
        ):
            await manager.approve("pending-t")

        update.assert_not_called()
        mock_relational_store.mark_pending.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_delete_of_already_archived_target_is_still_noop(self, mock_relational_store, memory_config):
        """Unchanged-but-archived targets keep the idempotent behaviour."""
        mock_relational_store.get_pending.return_value = self._target_record(PendingResolutionAction.DELETE)
        manager = MemoryManager(
            memory_config, user_id="test_user", relational=mock_relational_store, approval_required=True
        )

        archived = SemanticMemory(content="Works at Acme", status=MemoryStatus.ARCHIVED)
        with (
            patch.object(manager, "get_memory", return_value=archived),
            patch.object(manager, "update_memory", return_value=archived),
        ):
            await manager.approve("pending-t")

        mock_relational_store.mark_pending.assert_called_once_with("pending-t", "approved")

    @pytest.mark.asyncio
    async def test_second_correction_of_the_same_target_is_refused_after_a_real_first_correction(
        self, mock_vector_store, mock_relational_store, mock_embedding, memory_config
    ):
        """End to end through the real ``correct_memory``: the demotion it persists is what the guard reads back."""
        docs: dict[str, VectorDocument] = {}

        async def _upsert(_collection, documents):
            for doc in documents:
                docs[doc.id] = doc
            return [doc.id for doc in documents]

        async def _get(_collection, ids):
            return [docs[i] for i in ids if i in docs]

        mock_vector_store.upsert.side_effect = _upsert
        mock_vector_store.get.side_effect = _get
        target = SemanticMemory(id="mem-old", content="Works at Acme", embedding=[0.1] * 768)
        seeded = semantic_to_doc(target)
        seeded.metadata["namespaces"] = ["global"]
        docs[target.id] = seeded

        records = {
            pid: self._target_record(PendingResolutionAction.CORRECT).model_copy(
                update={"id": pid, "content": new, "memory_data": {"content": new}}
            )
            for pid, new in (("pending-a", "Works at Google"), ("pending-b", "Works at Initech"))
        }
        mock_relational_store.get_pending.side_effect = lambda pid: records[pid]
        manager = MemoryManager(
            memory_config,
            user_id="test_user",
            vector=mock_vector_store,
            relational=mock_relational_store,
            embedding=mock_embedding,
            approval_required=True,
        )

        await manager.approve("pending-a")
        with pytest.raises(PendingTargetChangedError):
            await manager.approve("pending-b")

        resolved = [call.args for call in mock_relational_store.mark_pending.call_args_list]
        assert resolved == [("pending-a", "approved")]
