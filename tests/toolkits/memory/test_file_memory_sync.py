"""Unit tests for File-as-Memory Local-First synchronization engine."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.file_sync import (
    FileMemoryCategory,
    FileMemoryEntry,
    FileMemoryStore,
    FileMemorySyncEngine,
    FileMemoryTopology,
    LenientMarkdownParser,
    MemoryAnchorFormatter,
)


def test_parser_basic_headings():
    """Verify parsing naturally formatted markdown sections with line numbers."""
    content = (
        "# Global Instructions\n"
        "Always be concise.\n"
        "\n"
        "## Coding Preferences\n"
        "- Use strict type hints.\n"
        "- Avoid Any.\n"
        "\n"
        "## Security Constraints\n"
        "Never run rm -rf on system paths.\n"
    )

    entries = LenientMarkdownParser.parse_document(content, "MEMORY.md")
    assert len(entries) == 3

    # First section
    assert entries[0].title == "Global Instructions"
    assert entries[0].line_start == 1
    assert "Always be concise." in entries[0].content
    assert entries[0].category == FileMemoryCategory.GENERAL

    # Second section
    assert entries[1].title == "Coding Preferences"
    assert entries[1].category == FileMemoryCategory.PREFERENCE
    assert entries[1].to_anchor() == "[source: MEMORY.md#L4-L7]"

    # Third section
    assert entries[2].title == "Security Constraints"
    assert entries[2].category == FileMemoryCategory.RULE
    assert "Never run rm -rf" in entries[2].content


def test_parser_frontmatter_stripping():
    """Ensure YAML frontmatter is stripped without shifting true physical line numbers."""
    content = (
        "---\n"
        "title: Project Rules\n"
        "author: admin\n"
        "---\n"
        "## Core Guidelines\n"
        "Follow test driven development.\n"
    )

    entries = LenientMarkdownParser.parse_document(content, "MEMORY.md")
    assert len(entries) == 1
    assert entries[0].title == "Core Guidelines"
    # Lines 1-4 are frontmatter, line 5 is heading
    assert entries[0].line_start == 5
    assert entries[0].to_anchor() == "[source: MEMORY.md#L5-L6]"


def test_file_store_atomic_write_and_daily_note(tmp_path: Path):
    """Test atomic file write and daily note append."""
    topology = FileMemoryTopology(root_dir=tmp_path)
    store = FileMemoryStore(topology)
    store.ensure_topology()

    assert topology.daily_dir_path.is_dir()
    assert topology.archive_dir_path.is_dir()

    # 1. Atomic write to main file
    store.write_atomic(topology.main_file_path, "# Main Memory\n\nUser likes dark mode.\n")
    assert topology.main_file_path.is_file()

    entries = store.read_entries(topology.main_file_path)
    assert len(entries) == 1
    assert "User likes dark mode." in entries[0].content

    # 2. Daily note append
    now = datetime(2026, 9, 17, 12, 0, 0, tzinfo=UTC)
    note_entry = store.append_daily_note(
        text="Investigated Redis cluster memory usage.",
        target_date=now,
        title="Redis Investigation",
    )
    assert note_entry is not None
    assert "Redis Investigation" in note_entry.title
    assert note_entry.category == FileMemoryCategory.EPISODIC

    daily_file = topology.get_daily_file_path(now)
    assert daily_file.is_file()
    daily_content = daily_file.read_text(encoding="utf-8")
    assert "Investigated Redis cluster" in daily_content


def test_anchor_formatter():
    """Verify anchor citation formatting and batch assembly."""
    entry = FileMemoryEntry(
        id="fmem_123",
        content="Prefer pytest over unittest.",
        source_file="MEMORY.md",
        line_start=15,
        line_end=18,
        category=FileMemoryCategory.PREFERENCE,
        title="Testing Convention",
    )

    single_block = MemoryAnchorFormatter.format_entry(entry)
    assert "### Testing Convention [source: MEMORY.md#L15-L18]" in single_block
    assert "Prefer pytest over unittest." in single_block

    batch_block = MemoryAnchorFormatter.format_batch([entry])
    assert "<workspace_memory_context>" in batch_block
    assert "[source: MEMORY.md#L15-L18]" in batch_block
    assert "</workspace_memory_context>" in batch_block


@pytest.mark.asyncio
async def test_sync_engine_ingress_and_external_change(tmp_path: Path):
    """Verify sync engine lazy freshness check and incremental change ingestion."""
    topology = FileMemoryTopology(root_dir=tmp_path)
    store = FileMemoryStore(topology)
    store.ensure_topology()

    mock_manager = MagicMock()
    mock_manager.add_knowledge = AsyncMock()

    engine = FileMemorySyncEngine(store=store, memory_manager=mock_manager)

    # 1. First probe when empty -> no changes
    report1 = await engine.check_and_sync_on_ingress()
    assert not report1.has_changes
    assert mock_manager.add_knowledge.call_count == 0

    # 2. Simulate external user editing MEMORY.md
    store.write_atomic(
        topology.main_file_path,
        "## User Coding Style\n- Python strict typing only.\n",
    )

    # 3. Next ingress probe should detect change and ingest
    report2 = await engine.check_and_sync_on_ingress()
    assert report2.has_changes
    assert report2.added_count == 1
    assert mock_manager.add_knowledge.call_count == 1

    added_kwargs = mock_manager.add_knowledge.call_args.kwargs
    assert "Python strict typing" in added_kwargs["content"]
    assert "file:MEMORY.md" in added_kwargs["tags"]

    # 4. Immediate second probe without file change -> zero re-sync overhead
    mock_manager.add_knowledge.reset_mock()
    report3 = await engine.check_and_sync_on_ingress()
    assert not report3.has_changes
    assert mock_manager.add_knowledge.call_count == 0


@pytest.mark.asyncio
async def test_sync_engine_persist_episodic_note(tmp_path: Path):
    """Verify persisting episodic notes through sync engine directly writes to file and backend."""
    topology = FileMemoryTopology(root_dir=tmp_path)
    store = FileMemoryStore(topology)
    store.ensure_topology()

    mock_manager = MagicMock()
    mock_manager.add_knowledge = AsyncMock()

    engine = FileMemorySyncEngine(store=store, memory_manager=mock_manager)

    entry = await engine.persist_episodic_note(
        text="Configured Celery broker with TLS.",
        title="Celery TLS Setup",
    )
    assert entry is not None
    assert mock_manager.add_knowledge.call_count == 1

    # Ensure file was actually created on disk
    assert any(topology.daily_dir_path.glob("*.md"))


def test_parser_fenced_code_block_with_comments():
    """Verify code blocks with internal # comments are never torn into separate headings."""
    content = (
        "# Root Header\n"
        "\n"
        "## Coding Rules\n"
        "Here is some configuration code:\n"
        "```python\n"
        "# This comment should not become a heading!\n"
        "def configure():\n"
        "    # Another internal comment\n"
        "    return {'mode': 'strict'}\n"
        "```\n"
        "Additional trailing instructions.\n"
    )

    entries = LenientMarkdownParser.parse_document(content, "MEMORY.md")
    assert len(entries) == 2

    # Root entry
    assert entries[0].title == "Root Header"
    assert entries[0].line_start == 1

    # Second entry must contain the entire code block intact
    coding_rules = entries[1]
    assert coding_rules.title == "Coding Rules"
    assert coding_rules.line_start == 3
    assert coding_rules.line_end == 11
    assert "def configure():" in coding_rules.content
    assert "# This comment should not become a heading!" in coding_rules.content
    assert "# Another internal comment" in coding_rules.content
    assert "Additional trailing instructions." in coding_rules.content


def test_parser_tilde_code_block_and_unclosed_fence():
    """Verify ~~~ fences and unclosed code block fences are handled gracefully."""
    content = (
        "## Bash Snippet\n"
        "~~~bash\n"
        "# Shell comment\n"
        "echo 'hello'\n"
        "~~~\n"
        "## Unclosed Fence\n"
        "```yaml\n"
        "# Unclosed yaml comment\n"
        "key: value\n"
    )

    entries = LenientMarkdownParser.parse_document(content, "MEMORY.md")
    assert len(entries) == 2
    assert entries[0].title == "Bash Snippet"
    assert "echo 'hello'" in entries[0].content
    assert entries[1].title == "Unclosed Fence"
    assert "key: value" in entries[1].content

