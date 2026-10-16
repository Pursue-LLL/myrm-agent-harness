"""Tests for sandbox path utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.paths.archive_paths import (
    get_compacted_output_path,
    get_content_addressed_compacted_metadata_path,
    get_content_addressed_compacted_output_path,
    get_content_addressed_compacted_restore_map_path,
    get_context_archive_sidecar_path_candidates,
)
from myrm_agent_harness.runtime.paths.execution_paths import (
    CONTEXT_SUBDIRS,
    LEGACY_WORKSPACE_ROOT,
    PERSISTENT_ROOT_ENV,
    ensure_context_dir_exists,
    get_context_file_path,
    get_context_root,
    get_context_session_dir,
    get_context_subdir,
    get_memories_root,
    get_persistent_root,
    get_scratchpad_path,
    get_system_config_path,
    get_workspace_relative_path,
    get_workspace_root,
    is_context_path,
    sanitize_filename,
    sanitize_path_segment,
)

_SHA256 = "ab" * 32


def test_default_roots() -> None:
    assert get_persistent_root() == "/persistent"
    assert get_workspace_root() == "/persistent/workspace"
    assert get_context_root() == "/persistent/.context"
    assert get_memories_root() == "/persistent/.memories"
    assert LEGACY_WORKSPACE_ROOT == "/workspace"


def test_every_root_follows_the_environment_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, "/data/harness")

    assert get_persistent_root() == "/data/harness"
    assert get_workspace_root() == "/data/harness/workspace"
    assert get_context_root() == "/data/harness/.context"
    assert get_memories_root() == "/data/harness/.memories"
    assert get_system_config_path("settings.json") == "/data/harness/.context/system/settings.json"
    assert get_scratchpad_path("chat_abc", "n.txt") == "/data/harness/.context/chat_abc/scratchpad/n.txt"


@pytest.mark.parametrize("configured", ["", "   ", "/"])
def test_a_blank_environment_value_means_the_default_root(monkeypatch: pytest.MonkeyPatch, configured: str) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, configured)

    assert get_persistent_root() == "/persistent"


def test_a_trailing_slash_does_not_leak_into_derived_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, " /data/harness/ ")

    assert get_persistent_root() == "/data/harness"
    assert get_context_root() == "/data/harness/.context"
    assert get_workspace_relative_path("/data/harness/.context/chat/f.txt") == ".context/chat/f.txt"


def test_relative_paths_and_context_membership_follow_the_relocated_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, "/data/harness")

    assert get_workspace_relative_path("/data/harness/workspace/p/f.py") == "workspace/p/f.py"
    assert get_workspace_relative_path("/persistent/workspace/p/f.py") == "persistent/workspace/p/f.py"
    assert is_context_path("/data/harness/.context/chat/f.txt") is True
    assert is_context_path("/persistent/.context/chat/f.txt") is False


def test_archive_paths_follow_the_relocated_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, "/data/harness")

    output = get_content_addressed_compacted_output_path("chat_abc", "web_search", _SHA256, 12)
    assert output == f"/data/harness/.context/chat_abc/compacted/sha256/ab/web_search_{_SHA256[:24]}_12.txt"
    assert get_content_addressed_compacted_metadata_path("chat_abc", "web_search", _SHA256, 12) == f"{output}.meta.json"
    assert (
        get_content_addressed_compacted_restore_map_path("chat_abc", "web_search", _SHA256, 12)
        == f"{output}.restore.json"
    )
    assert get_compacted_output_path("chat_abc", "bash").startswith("/data/harness/.context/chat_abc/compacted/bash_")
    assert get_context_archive_sidecar_path_candidates(".context/chat/compacted/r.txt") == (
        ".context/chat/compacted/r.txt.restore.json",
        "/data/harness/.context/chat/compacted/r.txt.restore.json",
    )
    assert get_context_archive_sidecar_path_candidates("/workspace/a/r.txt") == (
        "/workspace/a/r.txt.restore.json",
        "/data/harness/workspace/a/r.txt.restore.json",
    )


def test_content_addressed_path_rejects_a_malformed_digest() -> None:
    with pytest.raises(ValueError, match="64-character"):
        get_content_addressed_compacted_output_path("chat_abc", "web_search", "abc", 1)


def test_context_subdirs() -> None:
    assert CONTEXT_SUBDIRS["compacted"] == "compacted"
    assert CONTEXT_SUBDIRS["scratchpad"] == "scratchpad"


def test_get_compacted_output_path() -> None:
    path = get_compacted_output_path("chat_abc", "web_search")
    assert path.startswith("/persistent/.context/chat_abc/compacted/web_search_")
    assert path.endswith(".txt")


def test_get_compacted_output_path_compressed() -> None:
    path = get_compacted_output_path("chat_abc", "web_search", compressed=True)
    assert path.endswith(".txt.gz")


def test_get_scratchpad_path() -> None:
    path = get_scratchpad_path("chat_abc", "notes.txt")
    assert path == "/persistent/.context/chat_abc/scratchpad/notes.txt"


def test_get_system_config_path() -> None:
    path = get_system_config_path("settings.json")
    assert path == "/persistent/.context/system/settings.json"


def test_get_context_session_dir() -> None:
    path = get_context_session_dir("chat_abc")
    assert path == "/persistent/.context/chat_abc"


def test_get_context_subdir() -> None:
    path = get_context_subdir("chat_abc", "compacted")
    assert path == "/persistent/.context/chat_abc/compacted"


def test_get_context_file_path() -> None:
    path = get_context_file_path("chat_abc", "compacted", "output.txt")
    assert path == "/persistent/.context/chat_abc/compacted/output.txt"


def test_get_workspace_relative_path_persistent() -> None:
    result = get_workspace_relative_path("/persistent/.context/chat_abc/file.txt")
    assert result == ".context/chat_abc/file.txt"


def test_get_workspace_relative_path_legacy() -> None:
    result = get_workspace_relative_path("/workspace/project/file.py")
    assert result == "project/file.py"


def test_get_workspace_relative_path_other() -> None:
    result = get_workspace_relative_path("/tmp/file.txt")
    assert result == "tmp/file.txt"


def test_ensure_context_dir_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, str(tmp_path))

    path = ensure_context_dir_exists("chat_abc")

    assert path == str(tmp_path / ".context" / "chat_abc")
    assert Path(path).is_dir()


def test_ensure_context_dir_exists_with_subdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PERSISTENT_ROOT_ENV, str(tmp_path))

    path = ensure_context_dir_exists("chat_abc", "compacted")

    assert path == str(tmp_path / ".context" / "chat_abc" / "compacted")
    assert Path(path).is_dir()


def test_sanitize_path_segment_normal() -> None:
    assert sanitize_path_segment("chat_abc123") == "chat_abc123"


def test_sanitize_path_segment_traversal() -> None:
    result = sanitize_path_segment("../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result


def test_sanitize_path_segment_special_chars() -> None:
    result = sanitize_path_segment("tool@name#123")
    assert "@" not in result
    assert "#" not in result


def test_sanitize_path_segment_empty() -> None:
    result = sanitize_path_segment("")
    assert result == "default"


def test_sanitize_filename_normal() -> None:
    assert sanitize_filename("report.txt") == "report.txt"


def test_sanitize_filename_traversal() -> None:
    result = sanitize_filename("../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result


def test_sanitize_filename_empty() -> None:
    result = sanitize_filename("")
    assert result == "file.txt"


def test_is_context_path() -> None:
    assert is_context_path("/persistent/.context/chat_abc/file.txt") is True
    assert is_context_path("/persistent/workspace/file.py") is False


@pytest.mark.asyncio
async def test_track_context_file_access_non_context_path() -> None:
    from myrm_agent_harness.runtime.paths.access_tracking import track_context_file_access_if_needed

    await track_context_file_access_if_needed("/tmp/not_context.txt")


@pytest.mark.asyncio
async def test_track_context_file_access_no_session() -> None:
    from unittest.mock import patch

    from myrm_agent_harness.runtime.paths.access_tracking import track_context_file_access_if_needed

    with patch(
        "myrm_agent_harness.runtime.paths.access_tracking._cached_get_current_chat_id",
        return_value=None,
    ):
        import myrm_agent_harness.runtime.paths.access_tracking as sp

        sp._cached_get_current_chat_id = lambda: None
        await track_context_file_access_if_needed("/persistent/.context/chat_abc/file.txt")
