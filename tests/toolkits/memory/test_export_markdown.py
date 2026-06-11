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

    def test_procedural_includes_rule_structure(self) -> None:
        entry = {
            "id": "rule-001",
            "content": "Check dir before file creation",
            "created_at": "2024-03-01T00:00:00+00:00",
            "updated_at": "2024-03-01T00:00:00+00:00",
            "metadata": {},
            "trigger": "User requests file creation",
            "action": "Verify target directory exists",
            "reasoning": "Prevents write errors",
            "application": "Multi-level paths only",
            "priority": 5,
            "tool_name": "file_write",
            "tool_rule_priority": "critical",
            "source": "user_extracted",
            "status": "active",
            "pinned": True,
            "access_count": 7,
            "user_rating": 0.9,
            "language": "en",
        }
        result = _memory_to_markdown(entry, "procedural")
        assert "type: procedural" in result
        assert "trigger: User requests file creation" in result
        assert "action: Verify target directory exists" in result
        assert "priority: 5" in result
        assert "tool_name: file_write" in result
        assert "tool_rule_priority: critical" in result
        assert "source: user_extracted" in result
        assert "status: active" in result
        assert "pinned: true" in result
        assert "access_count: 7" in result
        assert "language: en" in result
        assert "user_rating: 0.9" in result
        assert "## Reasoning" in result
        assert "Prevents write errors" in result
        assert "## Application" in result
        assert "Multi-level paths only" in result
        assert "Check dir before file creation" in result

    def test_procedural_without_tool_name(self) -> None:
        entry = {
            "id": "rule-002",
            "content": "Global rule content",
            "created_at": "2024-03-01",
            "updated_at": "2024-03-01",
            "metadata": {},
            "trigger": "Any request",
            "action": "Be polite",
            "priority": 0,
            "source": "user_extracted",
            "status": "active",
        }
        result = _memory_to_markdown(entry, "procedural")
        assert "trigger: Any request" in result
        assert "action: Be polite" in result
        assert "tool_name" not in result
        assert "tool_rule_priority" not in result

    def test_procedural_without_reasoning_application(self) -> None:
        entry = {
            "id": "rule-003",
            "content": "Simple rule",
            "created_at": "2024-03-01",
            "updated_at": "2024-03-01",
            "metadata": {},
            "trigger": "trigger text",
            "action": "action text",
        }
        result = _memory_to_markdown(entry, "procedural")
        assert "## Reasoning" not in result
        assert "## Application" not in result
        assert "Simple rule" in result


class TestProceduralExportIntegration:
    """Integration: real ProceduralMemory → model_dump → _memory_to_markdown (no mocks)."""

    def test_real_procedural_model_dump_roundtrip(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        rule = ProceduralMemory(
            content="Always verify directory exists before writing files",
            trigger="User asks to create a file in a nested path",
            action="Check each parent directory; create missing ones with mkdir -p semantics",
            reasoning="Prevents FileNotFoundError on deeply nested writes",
            application="Only for paths with depth > 1; skip for root-level writes",
            priority=5,
            tool_name="file_write",
            tool_rule_priority="critical",
            source="user_extracted",
            pinned=True,
        )
        dumped = rule.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "procedural")

        assert "type: procedural" in md
        assert f"id: {rule.id}" in md
        assert "trigger: User asks to create a file in a nested path" in md
        assert "action: Check each parent directory" in md
        assert "priority: 5" in md
        assert "tool_name: file_write" in md
        assert "tool_rule_priority: critical" in md
        assert "source: user_extracted" in md
        assert "status: active" in md
        assert "pinned: true" in md
        assert f"access_count: {rule.access_count}" in md
        assert "language: en" in md
        assert "## Reasoning" in md
        assert "Prevents FileNotFoundError" in md
        assert "## Application" in md
        assert "Only for paths with depth > 1" in md
        assert "Always verify directory exists" in md

    def test_real_procedural_global_rule_no_tool(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        rule = ProceduralMemory(
            content="Use Chinese when user writes in Chinese",
            trigger="User message language is Chinese",
            action="Respond in Chinese",
            priority=0,
            source="user_extracted",
        )
        dumped = rule.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "procedural")

        assert "tool_name" not in md
        assert "tool_rule_priority" not in md
        assert "trigger: User message language is Chinese" in md
        assert "action: Respond in Chinese" in md
        assert "source: user_extracted" in md

    def test_real_procedural_no_reasoning_application(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        rule = ProceduralMemory(
            content="Simple rule",
            trigger="trigger",
            action="action",
        )
        dumped = rule.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "procedural")

        assert "## Reasoning" not in md
        assert "## Application" not in md
        assert "Simple rule" in md

    def test_real_procedural_chinese_language(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import ProceduralMemory

        rule = ProceduralMemory(
            content="使用中文回复用户",
            trigger="用户使用中文提问",
            action="以中文回复",
            language="zh",
        )
        dumped = rule.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "procedural")

        assert "language: zh" in md
        assert "trigger: 用户使用中文提问" in md
        assert "使用中文回复用户" in md

    def test_real_episodic_memory_roundtrip(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import EpisodicMemory

        mem = EpisodicMemory(
            content="Had a meeting about project Alpha",
            related_entities=["Alice", "ProjectAlpha"],
            importance=0.8,
        )
        dumped = mem.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "episodic")

        assert "type: episodic" in md
        assert "Had a meeting about project Alpha" in md
        assert "event_type: conversation" in md
        assert "importance: 0.8" in md
        assert "related_entities: [Alice, ProjectAlpha]" in md
        assert "trigger" not in md
        assert "## Reasoning" not in md

    def test_semantic_memory_with_full_metadata(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import SemanticMemory

        mem = SemanticMemory(
            content="User prefers dark mode",
            importance=0.9,
            confidence=0.95,
            language="zh",
            preference_type="explicit",
            tags=["ui", "theme"],
        )
        dumped = mem.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "semantic")

        assert "type: semantic" in md
        assert "User prefers dark mode" in md
        assert "importance: 0.9" in md
        assert "confidence: 0.95" in md
        assert "language: zh" in md
        assert "preference_type: explicit" in md
        assert "tags: [ui, theme]" in md
        assert "trigger" not in md
        assert "## Reasoning" not in md

    def test_conversation_memory_preserves_raw_exchange(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import ConversationMemory

        mem = ConversationMemory(
            content="User asked about dark mode",
            raw_exchange="User: How do I enable dark mode?\nAI: Go to Settings > Theme > Dark.",
            importance=0.7,
            project_id="proj-abc",
            topic_id="topic-ui",
            related_entities=["dark_mode", "settings"],
        )
        dumped = mem.model_dump(mode="json", exclude={"embedding", "raw_embedding", "summary_embedding"})
        md = _memory_to_markdown(dumped, "conversation")

        assert "type: conversation" in md
        assert "importance: 0.7" in md
        assert "project_id: proj-abc" in md
        assert "topic_id: topic-ui" in md
        assert "related_entities: [dark_mode, settings]" in md
        assert "## Summary" in md
        assert "User asked about dark mode" in md
        assert "## Original Exchange" in md
        assert "How do I enable dark mode?" in md

    def test_claim_memory_roundtrip(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import ClaimMemory

        mem = ClaimMemory(
            content="Python is preferred",
            claim_key="lang-pref",
            title="Language Preference",
            claim_text="User consistently uses Python",
            evidence_count=5,
            confidence=0.9,
            freshness="fresh",
        )
        dumped = mem.model_dump(mode="json")
        md = _memory_to_markdown(dumped, "claim")

        assert "type: claim" in md
        assert "claim_key: lang-pref" in md
        assert "title: Language Preference" in md
        assert "evidence_count: 5" in md
        assert "confidence: 0.9" in md
        assert "freshness: fresh" in md
        assert "## Claim" in md
        assert "User consistently uses Python" in md

    def test_integration_memory_roundtrip(self) -> None:
        from myrm_agent_harness.toolkits.memory.types import IntegrationMemory

        mem = IntegrationMemory(
            content="PR #42: Fix login bug",
            provider="github",
            title="Fix login bug",
            summary="Resolved authentication timeout",
            importance=0.8,
            tags=["bugfix", "auth"],
        )
        dumped = mem.model_dump(mode="json", exclude={"embedding"})
        md = _memory_to_markdown(dumped, "integration")

        assert "type: integration" in md
        assert "provider: github" in md
        assert "title: Fix login bug" in md
        assert "importance: 0.8" in md
        assert "tags: [bugfix, auth]" in md
        assert "## Summary" in md
        assert "Resolved authentication timeout" in md


class TestYamlSafeValue:
    """Verify that newlines in field values don't break YAML frontmatter."""

    def test_procedural_trigger_with_newline(self) -> None:
        d = {
            "id": "safe-001",
            "content": "rule content",
            "trigger": "When user asks\nabout Python version",
            "action": "Recommend 3.12",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        md = _memory_to_markdown(d, "procedural")
        lines = md.split("\n")
        first_end = lines.index("---", 1)
        frontmatter_block = lines[1:first_end]
        trigger_lines = [l for l in frontmatter_block if l.startswith("trigger:")]
        assert len(trigger_lines) == 1, "trigger should be a single frontmatter line"
        assert "\\n" in trigger_lines[0], "newline should be escaped"
        orphan = [l for l in frontmatter_block if l.strip() == "about Python version"]
        assert not orphan, "newline content must not become orphan line"

    def test_claim_title_with_newline(self) -> None:
        d = {
            "id": "safe-002",
            "content": "pref",
            "claim_key": "k",
            "title": "UI Preference:\nDark Mode",
            "evidence_count": 1,
            "confidence": 0.8,
            "freshness": "fresh",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        md = _memory_to_markdown(d, "claim")
        lines = md.split("\n")
        first_end = lines.index("---", 1)
        frontmatter_block = lines[1:first_end]
        title_lines = [l for l in frontmatter_block if l.startswith("title:")]
        assert len(title_lines) == 1
        orphan = [l for l in frontmatter_block if l.strip() == "Dark Mode"]
        assert not orphan

    def test_normal_values_unaffected(self) -> None:
        d = {
            "id": "safe-003",
            "content": "normal",
            "trigger": "simple trigger",
            "action": "simple action",
            "created_at": "2024-01-01T00:00:00+00:00",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }
        md = _memory_to_markdown(d, "procedural")
        assert "trigger: simple trigger" in md
        assert '"' not in md.split("trigger:")[1].split("\n")[0]


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
