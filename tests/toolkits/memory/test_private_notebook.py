"""Unit tests for Transparent Inspectable Model Private Notebook Suite.

Reference: OpenAI Codex rust-v0.153.0 / PR #42385 (features.context_management).
Tests Notes 5 tools, History 4 tools, LocalInspectableNoteStorage, and ModelPrivateNotebookManager.
"""

import tempfile
from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    HistoryContextManager,
    LocalInspectableNoteStorage,
    ModelPrivateNotebookManager,
    PrivateNotebookToolKit,
)


def test_local_inspectable_note_storage_crud_and_search() -> None:
    """Verify disk-based inspectable Markdown notes CRUD and keyword search."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalInspectableNoteStorage(Path(tmpdir) / ".myrm" / "agent_notes")

        # 1. Append/Create Note
        note1 = storage.append_note(
            title="auth_architecture",
            content_to_append="Decided to use stateless JWT with Argon2id for password hashing.",
            tags=["auth", "security"],
        )
        assert note1.title == "auth_architecture"
        assert "Argon2id" in note1.content
        assert "auth" in note1.tags

        # Verify disk file created
        disk_file = Path(tmpdir) / ".myrm" / "agent_notes" / "auth_architecture.md"
        assert disk_file.exists()
        assert "Argon2id" in disk_file.read_text(encoding="utf-8")

        # 2. Append additional content
        note1_updated = storage.append_note(
            title="auth_architecture",
            content_to_append="Added refresh token rotation with 7-day expiration.",
        )
        assert "refresh token rotation" in note1_updated.content

        # 3. Read note
        read_back = storage.read_note("auth_architecture")
        assert read_back is not None
        assert "Argon2id" in read_back.content
        assert "refresh token" in read_back.content

        # 4. Search notes
        search_hits = storage.search_notes("Argon2id")
        assert len(search_hits) >= 1
        assert search_hits[0].title == "auth_architecture"

        # 5. List notes metadata
        notes_list = storage.list_notes()
        assert len(notes_list) == 1
        assert notes_list[0].title == "auth_architecture"

        # 6. Rewrite note
        rewritten = storage.rewrite_note(
            title="auth_architecture",
            new_content="Fully replaced with Passkey WebAuthn architecture.",
            tags=["webauthn"],
        )
        assert "Passkey WebAuthn" in rewritten.content
        assert "Argon2id" not in rewritten.content

        # 7. Delete note
        deleted = storage.delete_note("auth_architecture")
        assert deleted is True
        assert not disk_file.exists()
        assert storage.read_note("auth_architecture") is None


def test_history_context_manager_indexing_and_search() -> None:
    """Verify indexing of multi-window conversation steps and cross-window retrieval."""
    history = HistoryContextManager()

    ctx_id_1 = "ctx_window_01"
    ctx_id_2 = "ctx_window_02"

    history.record_entry(ctx_id_1, role="user", content="请安装 cryptography 依赖并跑单测。")
    history.record_entry(
        ctx_id_1,
        role="tool",
        content="poetry run pytest tests/test_crypto.py -> 14 passed in 0.42s",
    )
    history.record_entry(ctx_id_1, role="assistant", content="加密模块 14 项单测已全绿通过。")

    history.record_entry(ctx_id_2, role="user", content="现在继续重构 API 路由。")

    # List contexts
    contexts = history.list_contexts()
    assert len(contexts) == 2
    ctx_ids = [c.context_id for c in contexts]
    assert ctx_id_1 in ctx_ids
    assert ctx_id_2 in ctx_ids

    # List entries for ctx_window_01
    entries_1 = history.list_entries(ctx_id_1)
    assert len(entries_1) == 3

    # Search history across contexts
    search_results = history.search_history("cryptography")
    assert len(search_results) >= 1
    assert any("cryptography" in e.content for e in search_results)

    search_pytest = history.search_history("pytest")
    assert len(search_pytest) >= 1
    assert search_pytest[0].context_id == ctx_id_1


def test_model_private_notebook_manager_and_tools_orchestration() -> None:
    """Verify ModelPrivateNotebookManager and 10-tool toolkit integration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = ModelPrivateNotebookManager(
            workspace_dir=tmpdir,
            initial_context_id="ctx_init_alpha",
        )
        tools: PrivateNotebookToolKit = manager.tools

        # 1. Use tool: append_note
        res_append = tools.append_note(
            title="database_schema",
            content="Table users: id, email, hashed_password.",
        )
        assert res_append["status"] == "success"
        assert res_append["title"] == "database_schema"

        # 2. Use tool: read_note
        res_read = tools.read_note(title="database_schema")
        assert res_read["found"] is True
        assert "Table users" in str(res_read["content"])

        # 3. Use tool: search_notes
        res_search = tools.search_notes(query="users")
        assert len(res_search) >= 1
        assert res_search[0]["title"] == "database_schema"

        # 4. Use tool: list_notes
        res_list = tools.list_notes()
        assert len(res_list) == 1
        assert res_list[0]["title"] == "database_schema"

        # 5. Record execution history turn
        manager.record_turn(role="user", content="请迁移数据库至 v2。")
        manager.record_turn(role="assistant", content="已执行 alembic upgrade head。")

        # 6. Use tool: list_history_contexts and search_history
        res_hist_contexts = tools.list_history_contexts()
        assert len(res_hist_contexts) >= 1

        res_hist_search = tools.search_history(query="alembic")
        assert len(res_hist_search) >= 1

        # 7. Use tool: new_context (Seamless rotation)
        res_new_ctx = tools.new_context(
            summary_reason="Token budget reached 90%, switching to fresh context while keeping database_schema note."
        )
        assert res_new_ctx["status"] == "ready"
        assert res_new_ctx["previous_context_id"] == "ctx_init_alpha"
        assert res_new_ctx["new_context_id"] != "ctx_init_alpha"
        assert int(str(res_new_ctx["carried_notes_count"])) >= 1

        # Note persists in new context
        assert manager.storage.read_note("database_schema") is not None
        # Handover note auto-created
        assert manager.storage.read_note("context_handovers") is not None

        # 8. Test auto_compact_fallback
        fallback_summary = manager.auto_compact_fallback(["turn 1", "turn 2", "turn 3"])
        assert "Fallback Compact Summary" in fallback_summary
