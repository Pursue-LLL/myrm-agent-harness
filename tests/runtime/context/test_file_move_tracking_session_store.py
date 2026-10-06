"""Unit tests for persistent file-move tracking session store."""

import shutil
import tempfile
from collections.abc import Generator

import pytest

from myrm_agent_harness.runtime.context.file_move_tracking_session_store import (
    PersistentFileMoveTrackingSessionStore,
)


@pytest.fixture
def temp_store_dir() -> Generator[str]:
    """Temporary storage directory for testing session store persistence."""
    tmp = tempfile.mkdtemp(prefix="test_file_move_store_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_resolve_new_and_existing_chat_id(temp_store_dir: str) -> None:
    """Test initial resolution and stable idempotent retrieval of ChatId."""
    store = PersistentFileMoveTrackingSessionStore(temp_store_dir)
    file_path = "/workspace/project/main.py"

    res1 = store.resolve_chat_id_for_path(file_path, title="Main Module")
    assert res1.is_newly_created is True
    assert res1.chat_id.startswith("chat-")
    assert res1.bound_path == "/workspace/project/main.py"

    meta1 = store.get_chat_meta(res1.chat_id)
    assert meta1 is not None
    assert meta1.title == "Main Module"
    assert meta1.message_count == 0

    # Second resolution with same path should yield same ChatId
    res2 = store.resolve_chat_id_for_path(file_path)
    assert res2.is_newly_created is False
    assert res2.chat_id == res1.chat_id
    assert res2.matched_via_history is False


def test_append_and_load_messages(temp_store_dir: str) -> None:
    """Test appending messages to JSONL and verifying metadata snapshots."""
    store = PersistentFileMoveTrackingSessionStore(temp_store_dir)
    res = store.resolve_chat_id_for_path("/docs/architecture.md")
    chat_id = res.chat_id

    # Append 3 messages
    store.append_message(chat_id, "user", "How should we organize the architecture?")
    store.append_message(chat_id, "assistant", "We should use a layered decoupled design.")
    store.append_message(chat_id, "user", "Sounds good, let's write it down.")

    meta = store.get_chat_meta(chat_id)
    assert meta is not None
    assert meta.message_count == 3

    # Load all messages
    msgs = store.load_messages(chat_id)
    assert len(msgs) == 3
    assert msgs[0].role == "user"
    assert msgs[1].content == "We should use a layered decoupled design."

    # Load with limit
    recent_msgs = store.load_messages(chat_id, limit=2)
    assert len(recent_msgs) == 2
    assert recent_msgs[0].role == "assistant"
    assert recent_msgs[1].content == "Sounds good, let's write it down."


def test_single_file_rename_and_move_tracking(temp_store_dir: str) -> None:
    """Test that moving/renaming a file preserves conversation history without whiteout."""
    store = PersistentFileMoveTrackingSessionStore(temp_store_dir)
    old_path = "/workspace/drafts/spec.md"
    new_path = "/workspace/specs/final_spec.md"

    # Register and write conversation on old path
    res = store.resolve_chat_id_for_path(old_path)
    chat_id = res.chat_id
    store.append_message(chat_id, "user", "Initial draft comments.")

    # File moved by user/system
    affected = store.track_file_moved(old_path, new_path)
    assert chat_id in affected

    # Resolving new path must return EXACT SAME chat_id with full history
    res_new = store.resolve_chat_id_for_path(new_path)
    assert res_new.chat_id == chat_id
    assert res_new.is_newly_created is False

    msgs_after_move = store.load_messages(res_new.chat_id)
    assert len(msgs_after_move) == 1
    assert msgs_after_move[0].content == "Initial draft comments."

    meta = store.get_chat_meta(chat_id)
    assert meta is not None
    assert meta.bound_path == "/workspace/specs/final_spec.md"
    assert "/workspace/drafts/spec.md" in meta.path_history

    # Resolving via historical old path also retrieves the same session
    res_old = store.resolve_chat_id_for_path(old_path)
    assert res_old.chat_id == chat_id
    assert res_old.matched_via_history is True


def test_directory_move_tracking_batch_migration(temp_store_dir: str) -> None:
    """Test directory rename automatically migrates all nested file ChatIds."""
    store = PersistentFileMoveTrackingSessionStore(temp_store_dir)
    dir_old = "/workspace/legacy_module"
    dir_new = "/workspace/core_module"

    file_a = f"{dir_old}/service.py"
    file_b = f"{dir_old}/sub/helper.py"

    res_a = store.resolve_chat_id_for_path(file_a)
    res_b = store.resolve_chat_id_for_path(file_b)

    store.append_message(res_a.chat_id, "user", "Service logic discussion")
    store.append_message(res_b.chat_id, "user", "Helper logic discussion")

    # Directory moved
    affected = store.track_file_moved(dir_old, dir_new, is_directory=True)
    assert res_a.chat_id in affected
    assert res_b.chat_id in affected

    # Check migrated paths
    new_file_a = f"{dir_new}/service.py"
    new_file_b = f"{dir_new}/sub/helper.py"

    res_migrated_a = store.resolve_chat_id_for_path(new_file_a)
    assert res_migrated_a.chat_id == res_a.chat_id
    assert len(store.load_messages(res_migrated_a.chat_id)) == 1

    res_migrated_b = store.resolve_chat_id_for_path(new_file_b)
    assert res_migrated_b.chat_id == res_b.chat_id
    assert len(store.load_messages(res_migrated_b.chat_id)) == 1


def test_disk_index_reload_and_deletion(temp_store_dir: str) -> None:
    """Test disk persistence reload across instances and chat deletion."""
    store1 = PersistentFileMoveTrackingSessionStore(temp_store_dir)
    res = store1.resolve_chat_id_for_path("/app/server.py")
    chat_id = res.chat_id
    store1.append_message(chat_id, "assistant", "Server initialized.")

    # Fresh store instance
    store2 = PersistentFileMoveTrackingSessionStore(temp_store_dir)
    res_reloaded = store2.resolve_chat_id_for_path("/app/server.py")
    assert res_reloaded.chat_id == chat_id
    assert res_reloaded.is_newly_created is False

    meta = store2.get_chat_meta(chat_id)
    assert meta is not None
    assert meta.message_count == 1

    # Delete chat
    deleted = store2.delete_chat(chat_id)
    assert deleted is True
    assert store2.get_chat_meta(chat_id) is None
    assert store2.load_messages(chat_id) == []
