"""Tests for TaskAttachment value object and KanbanTask.attachments field.

Covers:
- TaskAttachment creation, immutability, and serialization
- KanbanTask.attachments default, population, and to_dict() integration
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.kanban.types import (
    KanbanTask,
    TaskAttachment,
    TaskPriority,
    TaskStatus,
)

# ---------------------------------------------------------------------------
# TaskAttachment
# ---------------------------------------------------------------------------


class TestTaskAttachment:
    def test_creation(self) -> None:
        att = TaskAttachment(
            file_id="f1",
            filename="screenshot.png",
            mime_type="image/png",
            size_bytes=1024,
            content_ref="https://host/files/f1",
        )
        assert att.file_id == "f1"
        assert att.filename == "screenshot.png"
        assert att.mime_type == "image/png"
        assert att.size_bytes == 1024
        assert att.content_ref == "https://host/files/f1"

    def test_frozen_immutability(self) -> None:
        att = TaskAttachment(
            file_id="f1",
            filename="doc.pdf",
            mime_type="application/pdf",
            size_bytes=2048,
            content_ref="/api/v1/files/f1/content",
        )
        with pytest.raises(AttributeError):
            att.file_id = "f2"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            att.filename = "other.pdf"  # type: ignore[misc]
        with pytest.raises(AttributeError):
            att.size_bytes = 0  # type: ignore[misc]

    def test_to_dict(self) -> None:
        att = TaskAttachment(
            file_id="abc",
            filename="report.docx",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=5000,
            content_ref="vault://abc-uuid",
        )
        d = att.to_dict()
        assert d == {
            "file_id": "abc",
            "filename": "report.docx",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "size_bytes": 5000,
            "content_ref": "vault://abc-uuid",
        }

    def test_to_dict_return_type(self) -> None:
        att = TaskAttachment(
            file_id="f1",
            filename="a.png",
            mime_type="image/png",
            size_bytes=100,
            content_ref="http://x",
        )
        d = att.to_dict()
        assert isinstance(d, dict)
        assert all(isinstance(k, str) for k in d)

    def test_slots(self) -> None:
        att = TaskAttachment(
            file_id="f1",
            filename="a.png",
            mime_type="image/png",
            size_bytes=100,
            content_ref="http://x",
        )
        with pytest.raises((AttributeError, TypeError)):
            att.nonexistent = "value"  # type: ignore[attr-defined]

    def test_equality(self) -> None:
        a = TaskAttachment("f1", "a.png", "image/png", 100, "http://x")
        b = TaskAttachment("f1", "a.png", "image/png", 100, "http://x")
        assert a == b

    def test_inequality(self) -> None:
        a = TaskAttachment("f1", "a.png", "image/png", 100, "http://x")
        b = TaskAttachment("f2", "a.png", "image/png", 100, "http://x")
        assert a != b

    def test_content_ref_variants(self) -> None:
        """Verify content_ref supports all documented polymorphic formats."""
        for ref in [
            "https://host/files/abc",
            "vault://some-uuid-value",
            "data:image/png;base64,iVBORw0KGgo=",
        ]:
            att = TaskAttachment(
                file_id="f1", filename="test", mime_type="image/png",
                size_bytes=1, content_ref=ref,
            )
            assert att.content_ref == ref
            assert att.to_dict()["content_ref"] == ref


# ---------------------------------------------------------------------------
# KanbanTask.attachments
# ---------------------------------------------------------------------------


class TestKanbanTaskAttachments:
    def test_default_empty_list(self) -> None:
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Test",
            status=TaskStatus.READY,
            priority=TaskPriority.NORMAL,
        )
        assert task.attachments == []
        assert isinstance(task.attachments, list)

    def test_populate_attachments(self) -> None:
        att1 = TaskAttachment("f1", "img.png", "image/png", 1024, "http://x/f1")
        att2 = TaskAttachment("f2", "doc.pdf", "application/pdf", 2048, "http://x/f2")
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="With Attachments",
            attachments=[att1, att2],
        )
        assert len(task.attachments) == 2
        assert task.attachments[0].file_id == "f1"
        assert task.attachments[1].file_id == "f2"

    def test_to_dict_includes_attachments(self) -> None:
        att = TaskAttachment("f1", "img.png", "image/png", 512, "http://x/f1")
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Serialized",
            attachments=[att],
        )
        d = task.to_dict()
        assert "attachments" in d
        assert len(d["attachments"]) == 1  # type: ignore[arg-type]
        att_d = d["attachments"][0]  # type: ignore[index]
        assert att_d["file_id"] == "f1"
        assert att_d["filename"] == "img.png"

    def test_to_dict_empty_attachments(self) -> None:
        task = KanbanTask(task_id="t1", board_id="b1", title="NoAttach")
        d = task.to_dict()
        assert d["attachments"] == []

    def test_attachments_mutable_on_task(self) -> None:
        """KanbanTask is not frozen; attachments list can be modified."""
        task = KanbanTask(task_id="t1", board_id="b1", title="Mutable")
        att = TaskAttachment("f1", "a.png", "image/png", 100, "http://x")
        task.attachments.append(att)
        assert len(task.attachments) == 1
        assert task.attachments[0].file_id == "f1"

    def test_attachments_independent_per_instance(self) -> None:
        """Each KanbanTask instance should have its own attachments list."""
        t1 = KanbanTask(task_id="t1", board_id="b1", title="A")
        t2 = KanbanTask(task_id="t2", board_id="b1", title="B")
        t1.attachments.append(
            TaskAttachment("f1", "a.png", "image/png", 100, "http://x")
        )
        assert len(t1.attachments) == 1
        assert len(t2.attachments) == 0

    def test_to_dict_preserves_all_attachment_fields(self) -> None:
        att = TaskAttachment(
            file_id="f-xyz",
            filename="analysis.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=99999,
            content_ref="vault://big-file",
        )
        task = KanbanTask(
            task_id="t1",
            board_id="b1",
            title="Full Fields",
            attachments=[att],
        )
        att_dict = task.to_dict()["attachments"][0]  # type: ignore[index]
        assert att_dict == att.to_dict()

    def test_multiple_attachments_serialization(self) -> None:
        atts = [
            TaskAttachment(f"f{i}", f"file{i}.png", "image/png", i * 100, f"http://x/{i}")
            for i in range(5)
        ]
        task = KanbanTask(
            task_id="t1", board_id="b1", title="Multi",
            attachments=atts,
        )
        d = task.to_dict()
        assert len(d["attachments"]) == 5  # type: ignore[arg-type]
        for i, att_d in enumerate(d["attachments"]):  # type: ignore[arg-type]
            assert att_d["file_id"] == f"f{i}"
