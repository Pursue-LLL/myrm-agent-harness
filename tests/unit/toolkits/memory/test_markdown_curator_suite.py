# [POS]: tests/unit/toolkits/memory/test_markdown_curator_suite.py
# [INPUT]: myrm_agent_harness.toolkits.memory.markdown_curator
# [OUTPUT]: Unit tests for HumanReadableMarkdownBidiSyncAndMemoryCuratorStudioSuite (Item 101)

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    CuratedMemoryCategory,
    CuratedMemoryEntry,
    CuratedMemoryStatus,
    MarkdownBidiSyncEngine,
    MarkdownMemorySerializer,
    MemoryCuratorStudio,
)


def test_markdown_serializer_roundtrip() -> None:
    """Validate serialization of memory entries into Markdown and exact deserialization back."""
    serializer = MarkdownMemorySerializer()

    entries = [
        CuratedMemoryEntry(
            entry_id="pref-001",
            category=CuratedMemoryCategory.PREFERENCE,
            title="Formatting Style",
            content="Always use standard Ruff formatting with max line length 100",
            confidence=0.98,
            status=CuratedMemoryStatus.CONFIRMED,
            tags=["python", "style"],
        ),
        CuratedMemoryEntry(
            entry_id="fact-002",
            category=CuratedMemoryCategory.FACT,
            title="Database Port",
            content="PostgreSQL runs locally on port 5432 with isolated tenant volume",
            confidence=0.95,
            status=CuratedMemoryStatus.CONFIRMED,
            tags=["db", "infra"],
        ),
        CuratedMemoryEntry(
            entry_id="proc-003",
            category=CuratedMemoryCategory.PROCEDURE,
            title="Release Checklist",
            content="Run ruff check then pytest before git commit",
            confidence=0.75,
            status=CuratedMemoryStatus.PENDING_CONFIRMATION,
            tags=["ci", "git"],
        ),
    ]

    # 1. Serialize to Markdown
    md_content = serializer.serialize(entries, doc_title="Studio Memory Mirror")
    assert "---" in md_content
    assert "title: Studio Memory Mirror" in md_content
    assert "## Preferences" in md_content
    assert "## Facts" in md_content
    assert "## Procedures" in md_content
    assert "pref-001" in md_content
    assert "fact-002" in md_content

    # 2. Deserialize back
    parsed = serializer.deserialize(md_content)
    assert len(parsed) == 3

    by_id = {e.entry_id: e for e in parsed}
    assert "pref-001" in by_id
    assert by_id["pref-001"].title == "Formatting Style"
    assert by_id["pref-001"].category == CuratedMemoryCategory.PREFERENCE
    assert by_id["pref-001"].status == CuratedMemoryStatus.CONFIRMED
    assert "python" in by_id["pref-001"].tags

    assert "proc-003" in by_id
    assert by_id["proc-003"].status == CuratedMemoryStatus.PENDING_CONFIRMATION
    assert by_id["proc-003"].confidence == 0.75


def test_bidi_sync_human_precedence_and_deletion() -> None:
    """Validate human-in-the-loop precedence when syncing edits, additions, and deletions from Markdown."""
    sync_engine = MarkdownBidiSyncEngine()

    in_memory_store = {
        "fact-001": CuratedMemoryEntry(
            entry_id="fact-001",
            category=CuratedMemoryCategory.FACT,
            title="Client City",
            content="Client resides in Beijing",
            confidence=0.9,
            status=CuratedMemoryStatus.CONFIRMED,
        ),
        "fact-002": CuratedMemoryEntry(
            entry_id="fact-002",
            category=CuratedMemoryCategory.FACT,
            title="Outdated Framework",
            content="Project uses Vue 2",
            confidence=0.8,
            status=CuratedMemoryStatus.CONFIRMED,
        ),
    }

    # Simulated Markdown parsed list:
    # 1. fact-001 edited by human ("Beijing" -> "Shanghai")
    # 2. fact-002 deleted by human (missing from list)
    # 3. pref-new added by human
    markdown_entries = [
        CuratedMemoryEntry(
            entry_id="fact-001",
            category=CuratedMemoryCategory.FACT,
            title="Client City",
            content="Client resides in Shanghai (relocated in 2026)",
            confidence=1.0,
            status=CuratedMemoryStatus.CONFIRMED,
        ),
        CuratedMemoryEntry(
            entry_id="pref-new",
            category=CuratedMemoryCategory.PREFERENCE,
            title="Language Preference",
            content="Prefer Chinese documentation and code comments",
            confidence=1.0,
            status=CuratedMemoryStatus.CONFIRMED,
            tags=["i18n"],
        ),
    ]

    delta = sync_engine.apply_sync(in_memory_store, markdown_entries, hard_delete=False)

    assert len(delta.added_entries) == 1
    assert delta.added_entries[0].entry_id == "pref-new"

    assert len(delta.updated_entries) == 1
    assert delta.updated_entries[0].entry_id == "fact-001"
    assert "Shanghai" in in_memory_store["fact-001"].content

    assert "fact-002" in delta.deleted_entry_ids
    # When hard_delete=False, it should be marked as ARCHIVED
    assert in_memory_store["fact-002"].status == CuratedMemoryStatus.ARCHIVED


def test_curator_studio_human_gate_and_summary() -> None:
    """Validate curator studio operations: anti-misremembering gate, audit, erase, and metrics summary."""
    studio = MemoryCuratorStudio()

    # 1. High-confidence item auto-confirmed
    e1 = CuratedMemoryEntry(
        entry_id="mem-high",
        category=CuratedMemoryCategory.FACT,
        title="Python Version",
        content="Target is Python 3.13+",
        confidence=0.95,
    )
    studio.add_entry(e1)
    assert studio.get_entry("mem-high") is not None
    assert studio.get_entry("mem-high").status == CuratedMemoryStatus.CONFIRMED

    # 2. Low-confidence item intercepted by anti-misremembering gate
    e2 = CuratedMemoryEntry(
        entry_id="mem-low",
        category=CuratedMemoryCategory.PREFERENCE,
        title="Spicy Food Interest",
        content="User might enjoy spicy hotpot",
        confidence=0.65,
    )
    studio.add_entry(e2)
    assert studio.get_entry("mem-low").status == CuratedMemoryStatus.PENDING_CONFIRMATION

    # 3. Human audit: approve e2
    studio.audit_entry("mem-low", is_approved=True)
    assert studio.get_entry("mem-low").status == CuratedMemoryStatus.CONFIRMED

    # 4. Human audit: add e3 and reject
    e3 = CuratedMemoryEntry(
        entry_id="mem-guess",
        category=CuratedMemoryCategory.EXPERIENCE,
        title="Dubious Bug",
        content="Guessing memory leak in unused thread",
        confidence=0.5,
    )
    studio.add_entry(e3)
    studio.audit_entry("mem-guess", is_approved=False)
    assert studio.get_entry("mem-guess").status == CuratedMemoryStatus.REJECTED

    # 5. One-click privacy wipe: erase mem-high
    erased = studio.erase_entry("mem-high", hard_erase=True)
    assert erased is True
    assert studio.get_entry("mem-high") is None

    # 6. Check summary metrics
    summary = studio.get_summary()
    assert summary.total_entries == 2  # mem-low and mem-guess
    assert summary.confirmed_count == 1
    assert summary.rejected_count == 1
    assert summary.categories_breakdown["preference"] == 1
    assert summary.categories_breakdown["experience"] == 1
