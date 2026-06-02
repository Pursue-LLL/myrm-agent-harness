"""Tests for sandbox path utilities."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.execution_paths import (
    ARTIFACTS_ROOT,
    CONTEXT_ROOT,
    CONTEXT_SUBDIRS,
    LEGACY_SYSTEM_CONFIG_ROOT,
    LEGACY_WORKSPACE_ROOT,
    MEMORIES_ROOT,
    PERSISTENT_ROOT,
    SYSTEM_CONFIG_ROOT,
    WORKSPACE_ROOT,
    _sanitize_filename,
    _sanitize_path_segment,
    ensure_context_dir_exists,
    get_compacted_output_path,
    get_context_file_path,
    get_context_session_dir,
    get_context_subdir,
    get_scratchpad_path,
    get_system_config_path,
    get_workspace_relative_path,
    is_context_path,
    is_persistent_path,
)


def test_path_constants() -> None:
    assert PERSISTENT_ROOT == "/persistent"
    assert WORKSPACE_ROOT == "/persistent/workspace"
    assert CONTEXT_ROOT == "/persistent/.context"
    assert ARTIFACTS_ROOT == "/persistent/workspace/artifacts"
    assert MEMORIES_ROOT == "/persistent/.memories"
    assert SYSTEM_CONFIG_ROOT == "/persistent/.context/system"
    assert LEGACY_SYSTEM_CONFIG_ROOT == "/persistent/.claude"
    assert LEGACY_WORKSPACE_ROOT == "/workspace"


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


def test_ensure_context_dir_exists(tmp_path) -> None:
    import myrm_agent_harness.runtime.execution_paths as sp

    original = sp.CONTEXT_ROOT
    sp.CONTEXT_ROOT = str(tmp_path / ".context")
    try:
        path = ensure_context_dir_exists("chat_abc")
        assert path.endswith("chat_abc")
        from pathlib import Path

        assert Path(path).exists()
    finally:
        sp.CONTEXT_ROOT = original


def test_ensure_context_dir_exists_with_subdir(tmp_path) -> None:
    import myrm_agent_harness.runtime.execution_paths as sp

    original = sp.CONTEXT_ROOT
    sp.CONTEXT_ROOT = str(tmp_path / ".context")
    try:
        path = ensure_context_dir_exists("chat_abc", "compacted")
        assert path.endswith("compacted")
        from pathlib import Path

        assert Path(path).exists()
    finally:
        sp.CONTEXT_ROOT = original


def test_sanitize_path_segment_normal() -> None:
    assert _sanitize_path_segment("chat_abc123") == "chat_abc123"


def test_sanitize_path_segment_traversal() -> None:
    result = _sanitize_path_segment("../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result


def test_sanitize_path_segment_special_chars() -> None:
    result = _sanitize_path_segment("tool@name#123")
    assert "@" not in result
    assert "#" not in result


def test_sanitize_path_segment_empty() -> None:
    result = _sanitize_path_segment("")
    assert result == "default"


def test_sanitize_filename_normal() -> None:
    assert _sanitize_filename("report.txt") == "report.txt"


def test_sanitize_filename_traversal() -> None:
    result = _sanitize_filename("../../../etc/passwd")
    assert ".." not in result
    assert "/" not in result


def test_sanitize_filename_empty() -> None:
    result = _sanitize_filename("")
    assert result == "file.txt"


def test_is_persistent_path() -> None:
    assert is_persistent_path("/persistent/.context/file.txt") is True
    assert is_persistent_path("/tmp/file.txt") is False


def test_is_context_path() -> None:
    assert is_context_path("/persistent/.context/chat_abc/file.txt") is True
    assert is_context_path("/persistent/workspace/file.py") is False


@pytest.mark.asyncio
async def test_track_context_file_access_non_context_path() -> None:
    from myrm_agent_harness.runtime.execution_paths import track_context_file_access_if_needed

    await track_context_file_access_if_needed("/tmp/not_context.txt")


@pytest.mark.asyncio
async def test_track_context_file_access_no_session() -> None:
    from unittest.mock import patch

    from myrm_agent_harness.runtime.execution_paths import track_context_file_access_if_needed

    with patch(
        "myrm_agent_harness.runtime.execution_paths._cached_get_current_chat_id",
        return_value=None,
    ):
        import myrm_agent_harness.runtime.execution_paths as sp

        sp._cached_get_current_chat_id = lambda: None
        await track_context_file_access_if_needed("/persistent/.context/chat_abc/file.txt")
