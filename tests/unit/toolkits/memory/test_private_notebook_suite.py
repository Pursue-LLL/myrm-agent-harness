"""[POS]: tests/unit/toolkits/memory/test_private_notebook_suite.py
[INPUT]: Temporary sandbox directories, note operations, history turns, and context rotation triggers.
[OUTPUT]: Comprehensive test assertions verifying storage, history recall, toolkits, and context switching.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory import (
    HistoryContextManager,
    LocalInspectableNoteStorage,
    ModelPrivateNotebookManager,
    PrivateNotebookToolKit,
)


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Fixture providing an isolated temporary workspace directory."""
    return tmp_path / "sandbox_workspace"


def test_local_inspectable_note_storage(temp_workspace: Path) -> None:
    """Verify local markdown notes creation, appending, atomic rewrite, and keyword search."""
    notes_dir = temp_workspace / ".myrm" / "agent_notes"
    storage = LocalInspectableNoteStorage(notes_dir)

    # 1. Append creates note
    note = storage.append_note(
        "architecture_decisions",
        "## Decision 1\nAdopted Rust for performance critical sandbox isolation.",
    )
    assert note.title == "architecture_decisions"
    assert "Adopted Rust" in note.content

    # Verify physical file existence on disk
    expected_file = notes_dir / "architecture_decisions.md"
    assert expected_file.is_file()
    assert "Adopted Rust" in expected_file.read_text(encoding="utf-8")

    # 2. Append more content
    updated = storage.append_note(
        "architecture_decisions",
        "## Decision 2\nChose SQLite for single-node ACID local persistence.",
    )
    assert "Decision 1" in updated.content
    assert "Decision 2" in updated.content

    # 3. List notes
    metas = storage.list_notes()
    assert len(metas) == 1
    assert metas[0].title == "architecture_decisions"
    assert metas[0].line_count > 1

    # 4. Search notes
    hits = storage.search_notes("sqlite persistence")
    assert len(hits) == 1
    assert hits[0].title == "architecture_decisions"
    assert "SQLite" in hits[0].snippet

    # 5. Rewrite note (human correction / model update)
    rectified = storage.rewrite_note(
        "architecture_decisions",
        "## Corrected Decision\nReplaced SQLite with Turso embedded replica.",
    )
    assert "Turso" in rectified.content
    assert "Decision 1" not in rectified.content

    # 6. Delete note
    deleted = storage.delete_note("architecture_decisions")
    assert deleted is True
    assert not expected_file.exists()
    assert len(storage.list_notes()) == 0


def test_history_context_manager() -> None:
    """Verify archived multi-window interaction indexing and cross-context search."""
    history = HistoryContextManager()

    # Record turns in context 1
    history.record_entry("ctx_100", "user", "How do I configure Redis cache?", context_title="Redis Setup")
    history.record_entry("ctx_100", "assistant", "Use host 127.0.0.1 port 6379 with standard pool.")

    # Record turns in context 2
    history.record_entry("ctx_200", "user", "Docker port 6379 is already in use by postgres.", context_title="Port Conflict")
    history.record_entry("ctx_200", "assistant", "Run lsof -i :6379 to identify the occupying PID.")

    contexts = history.list_contexts()
    assert len(contexts) == 2

    # Verify chronological entries under ctx_100
    entries_100 = history.list_entries("ctx_100")
    assert len(entries_100) == 2
    assert entries_100[0].role == "user"
    assert entries_100[1].role == "assistant"

    # Read specific entry
    read_turn = history.read_entry("ctx_100", 1)
    assert read_turn is not None
    assert "127.0.0.1" in read_turn.content

    # Search across all contexts
    search_hits = history.search_history("6379")
    assert len(search_hits) == 3  # Both in ctx_100 and ctx_200
    contexts_found = {h.context_id for h in search_hits}
    assert "ctx_100" in contexts_found
    assert "ctx_200" in contexts_found


def test_model_private_notebook_manager_and_tools(temp_workspace: Path) -> None:
    """Verify complete toolkit exposure and smooth context rotation without losing notes."""
    manager = ModelPrivateNotebookManager(temp_workspace, initial_context_id="ctx_initial")
    tools: PrivateNotebookToolKit = manager.tools

    # 1. Model takes notes via tools
    res_append = tools.append_note(
        "failed_attempts",
        "- Attempt 1: Tried port 8080 (Permission Denied)\n- Attempt 2: Tried binding 0.0.0.0 (Firewall blocked)",
    )
    assert res_append["status"] == "success"

    res_list = tools.list_notes()
    assert len(res_list) == 1
    assert res_list[0]["title"] == "failed_attempts"

    res_read = tools.read_note("failed_attempts")
    assert res_read["found"] is True
    assert "Permission Denied" in str(res_read["content"])

    # 2. Record turns in active context
    manager.record_turn("user", "We are running low on tokens, please rotate context.")
    manager.record_turn("assistant", "Noting lessons to failed_attempts before switching.")

    # 3. Model triggers new_context tool
    res_switch = tools.new_context(
        summary_reason="Token budget exceeded; rotating context while preserving failed_attempts notes."
    )
    assert res_switch["status"] == "ready"
    assert res_switch["previous_context_id"] == "ctx_initial"
    new_ctx_id = str(res_switch["new_context_id"])
    assert new_ctx_id != "ctx_initial"
    assert manager.current_context_id == new_ctx_id

    # Notes are fully carried over and intact in the new context
    carried_notes = tools.list_notes()
    carried_titles = {n["title"] for n in carried_notes}
    assert "failed_attempts" in carried_titles
    assert "context_handovers" in carried_titles

    # History recalls previous turns across context boundary
    hist_search = tools.search_history("rotate context")
    assert len(hist_search) >= 1
    assert hist_search[0]["context_id"] == "ctx_initial"

    # Fallback auto compaction verification
    fallback_summary = manager.auto_compact_fallback(["line 1", "line 2", "line 3"])
    assert "Fallback Compact Summary" in fallback_summary
