"""Tests for export_markdown functionality in MemoryManagerImportExportMixin."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._manager.import_export import (
    _memory_to_markdown,
    _sanitize_filename,
)


class TestSanitizeFilename:
    def test_basic_ascii(self) -> None:
        assert _sanitize_filename("Hello World") == "Hello_World"

    def test_chinese(self) -> None:
        result = _sanitize_filename("用户偏好设置")
        assert "用户偏好设置" in result

    def test_special_chars_stripped(self) -> None:
        result = _sanitize_filename("test@#$%^&*()")
        assert "@" not in result
        assert "#" not in result

    def test_max_length(self) -> None:
        long_text = "a" * 100
        result = _sanitize_filename(long_text, max_len=60)
        assert len(result) <= 60

    def test_empty_input(self) -> None:
        assert _sanitize_filename("@#$%") == "untitled"

    def test_whitespace_collapse(self) -> None:
        result = _sanitize_filename("hello   world   test")
        assert "  " not in result


class TestMemoryToMarkdown:
    def test_basic_conversion(self) -> None:
        entry = {
            "id": "abc-123",
            "content": "User prefers dark mode",
            "created_at": "2024-01-15T10:30:00+00:00",
            "updated_at": "2024-01-15T10:30:00+00:00",
            "metadata": {},
        }
        result = _memory_to_markdown(entry, "semantic")
        assert "---" in result
        assert "id: abc-123" in result
        assert "type: semantic" in result
        assert "created_at: 2024-01-15T10:30:00+00:00" in result
        assert "User prefers dark mode" in result

    def test_with_tags(self) -> None:
        entry = {
            "id": "def-456",
            "content": "Some memory",
            "created_at": "2024-02-01T00:00:00+00:00",
            "updated_at": "2024-02-01T00:00:00+00:00",
            "metadata": {"tags": "preference,ui", "category": "settings"},
        }
        result = _memory_to_markdown(entry, "profile")
        assert "tags:" in result
        assert "preference" in result
        assert "ui" in result
        assert "settings" in result

    def test_frontmatter_format(self) -> None:
        entry = {
            "id": "test-id",
            "content": "Test content",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-01",
            "metadata": {},
        }
        result = _memory_to_markdown(entry, "episodic")
        lines = result.strip().split("\n")
        assert lines[0] == "---"
        close_idx = lines.index("---", 1)
        assert close_idx > 0
        content_start = close_idx + 1
        assert "Test content" in "\n".join(lines[content_start:])


class TestExportMarkdownIntegration:
    @pytest.fixture
    def tmp_export_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "export"

    @pytest.mark.asyncio
    async def test_export_creates_type_directories(self, tmp_export_dir: Path) -> None:
        mock_data = {
            "semantic": [
                {
                    "id": "mem-1",
                    "content": "I like Python",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                }
            ],
            "episodic": [
                {
                    "id": "mem-2",
                    "content": "Had a meeting about project X",
                    "created_at": "2024-01-02T00:00:00+00:00",
                    "updated_at": "2024-01-02T00:00:00+00:00",
                    "metadata": {},
                }
            ],
        }

        from myrm_agent_harness.toolkits.memory._manager.import_export import (
            MemoryManagerImportExportMixin,
        )

        mixin = MemoryManagerImportExportMixin()
        mixin.export_all = AsyncMock(return_value=mock_data)  # type: ignore[method-assign]

        counts = await mixin.export_markdown(tmp_export_dir)

        assert (tmp_export_dir / "semantic").is_dir()
        assert (tmp_export_dir / "episodic").is_dir()
        assert counts["semantic"] == 1
        assert counts["episodic"] == 1

        semantic_files = list((tmp_export_dir / "semantic").glob("*.md"))
        assert len(semantic_files) == 1

        content = semantic_files[0].read_text(encoding="utf-8")
        assert "id: mem-1" in content
        assert "I like Python" in content

    @pytest.mark.asyncio
    async def test_export_deduplicates_on_id(self, tmp_export_dir: Path) -> None:
        mock_data = {
            "semantic": [
                {
                    "id": "mem-1",
                    "content": "Updated content v2",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-05T00:00:00+00:00",
                    "metadata": {},
                }
            ],
        }

        from myrm_agent_harness.toolkits.memory._manager.import_export import (
            MemoryManagerImportExportMixin,
        )

        type_dir = tmp_export_dir / "semantic"
        type_dir.mkdir(parents=True, exist_ok=True)
        existing_file = type_dir / "old_file_mem-1.md"
        existing_file.write_text("---\nid: mem-1\ntype: semantic\n---\nOld content\n", encoding="utf-8")

        mixin = MemoryManagerImportExportMixin()
        mixin.export_all = AsyncMock(return_value=mock_data)  # type: ignore[method-assign]

        counts = await mixin.export_markdown(tmp_export_dir)

        assert counts["semantic"] == 1
        updated_content = existing_file.read_text(encoding="utf-8")
        assert "Updated content v2" in updated_content

    @pytest.mark.asyncio
    async def test_export_since_filter(self, tmp_export_dir: Path) -> None:
        from datetime import datetime, timezone

        mock_data = {
            "semantic": [
                {
                    "id": "old-mem",
                    "content": "Old memory",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                },
                {
                    "id": "new-mem",
                    "content": "New memory",
                    "created_at": "2024-06-01T00:00:00+00:00",
                    "updated_at": "2024-06-01T00:00:00+00:00",
                    "metadata": {},
                },
            ],
        }

        from myrm_agent_harness.toolkits.memory._manager.import_export import (
            MemoryManagerImportExportMixin,
        )

        mixin = MemoryManagerImportExportMixin()
        mixin.export_all = AsyncMock(return_value=mock_data)  # type: ignore[method-assign]

        since = datetime(2024, 3, 1, tzinfo=timezone.utc)
        counts = await mixin.export_markdown(tmp_export_dir, since_ts=since)

        assert counts["semantic"] == 1
        files = list((tmp_export_dir / "semantic").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "New memory" in content

    @pytest.mark.asyncio
    async def test_export_agent_id_filter(self, tmp_export_dir: Path) -> None:
        mock_data = {
            "semantic": [
                {
                    "id": "agent-a-mem",
                    "content": "Agent A knows this",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                    "scope": {"namespaces": ["agent:agent-a"]},
                },
                {
                    "id": "agent-b-mem",
                    "content": "Agent B knows this",
                    "created_at": "2024-01-01T00:00:00+00:00",
                    "updated_at": "2024-01-01T00:00:00+00:00",
                    "metadata": {},
                    "scope": {"namespaces": ["agent:agent-b"]},
                },
            ],
        }

        from myrm_agent_harness.toolkits.memory._manager.import_export import (
            MemoryManagerImportExportMixin,
        )

        mixin = MemoryManagerImportExportMixin()
        mixin.export_all = AsyncMock(return_value=mock_data)  # type: ignore[method-assign]

        counts = await mixin.export_markdown(tmp_export_dir, agent_id="agent-a")

        assert counts["semantic"] == 1
        files = list((tmp_export_dir / "semantic").glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert "Agent A knows this" in content
