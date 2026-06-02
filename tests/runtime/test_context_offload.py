"""Tests for context compress offload reliability features.

Tests compression failure fallback and quota checking.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.runtime.context.offload import (
    cleanup_session_context_files,
    create_compress_offload_callback,
)
from myrm_agent_harness.runtime.quota.errors import QuotaExceededError
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    CodeExecutor,
    ExecutionContext,
)


class MockAccessTracker:
    """Mock file access tracker for lifecycle tests."""

    def __init__(self) -> None:
        self.accesses: list[tuple[str, str]] = []
        self.deleted_sessions: list[str] = []

    async def record_access(self, path: str, session_id: str) -> None:
        self.accesses.append((path, session_id))

    async def delete_session_records(self, session_id: str) -> int:
        self.deleted_sessions.append(session_id)
        return 1


@pytest.fixture(autouse=True)
def mock_runtime_side_effects() -> Iterator[MockAccessTracker]:
    """Mock filesystem side effects that are outside the unit under test."""
    tracker = MockAccessTracker()
    with (
        patch("myrm_agent_harness.runtime.context.offload.ensure_context_dir_exists"),
        patch(
            "myrm_agent_harness.runtime.context.file_access_tracker.get_file_access_tracker",
            new=AsyncMock(return_value=tracker),
        ),
    ):
        yield tracker


class MockExecutor:
    """Mock sandbox executor for testing."""

    def __init__(self) -> None:
        self.written_files: dict[str, str | bytes] = {}

    async def file_exists(self, path: str) -> bool:
        return path in self.written_files

    async def read_file(self, path: str) -> str:
        content = self.written_files[path]
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return content

    async def read_file_bytes(self, path: str) -> bytes:
        content = self.written_files[path]
        if isinstance(content, bytes):
            return content
        return content.encode("utf-8")

    async def write_file(self, path: str, content: str) -> None:
        self.written_files[path] = content

    async def write_file_bytes(self, path: str, content: bytes) -> None:
        self.written_files[path] = content

    async def write_file_atomic(self, path: str, content: str) -> None:
        await self.write_file(path, content)

    async def write_file_bytes_atomic(self, path: str, content: bytes) -> None:
        await self.write_file_bytes(path, content)


class MockCleanupExecutor:
    """Mock executor for cleanup tests."""

    def __init__(self) -> None:
        self.workspace_path = "/tmp/workspace"
        self.executed_contexts: list[ExecutionContext] = []

    async def execute_bash(self, context: ExecutionContext) -> None:
        self.executed_contexts.append(context)


class MockQuotaChecker:
    """Mock quota checker for testing."""

    def __init__(self, allow_write: bool = True, remaining_quota: int = 1024000) -> None:
        self.allow_write = allow_write
        self.remaining_quota = remaining_quota
        self.check_calls: list[tuple[str, int]] = []

    async def check_write_allowed(self, session_id: str, write_size_bytes: int) -> bool:
        self.check_calls.append((session_id, write_size_bytes))
        return self.allow_write

    async def get_remaining_quota(self, session_id: str) -> int:
        return self.remaining_quota


@pytest.mark.asyncio
async def test_compression_failure_fallback_to_uncompressed() -> None:
    """Test that compression failure falls back to uncompressed write."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=True,
        compression_threshold=1000,
    )

    with patch(
        "myrm_agent_harness.runtime.context.offload.compress_content_async",
        side_effect=RuntimeError("Compression failed"),
    ):
        result_path = await callback(
            content="A" * 5000,
            tool_name="test_tool",
            scope_id="test_session",
        )

        assert len(executor.written_files) == 3
        assert result_path.path.endswith(".txt")
        assert not result_path.path.endswith(".txt.gz")
        assert not result_path.reused

        written_content = executor.written_files[result_path.path]
        assert isinstance(written_content, str)
        assert written_content == "A" * 5000
        restore_map_path = f"{result_path.path}.restore.json"
        restore_map = json.loads(str(executor.written_files[restore_map_path]))
        assert restore_map["archive_path"] == result_path.path
        assert restore_map["schema_version"] == 2
        assert restore_map["content_index"]["line_count"] == 1
        assert restore_map["recommended_ranges"]


@pytest.mark.asyncio
async def test_quota_check_allows_write_within_quota() -> None:
    """Test that write is allowed when within quota."""
    executor = MockExecutor()
    quota_checker = MockQuotaChecker(allow_write=True)

    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=quota_checker,
    )

    await callback(
        content="Test content",
        tool_name="test_tool",
        scope_id="test_session",
    )

    assert len(executor.written_files) == 3
    assert len(quota_checker.check_calls) == 1
    session_id, write_size = quota_checker.check_calls[0]
    assert session_id == "test_session"
    assert write_size >= len("Test content")


@pytest.mark.asyncio
async def test_quota_check_blocks_write_exceeding_quota() -> None:
    """Test that write is blocked when exceeding quota."""
    executor = MockExecutor()
    quota_checker = MockQuotaChecker(allow_write=False, remaining_quota=100)

    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=quota_checker,
    )

    with pytest.raises(QuotaExceededError) as exc_info:
        await callback(
            content="Large content" * 1000,
            tool_name="test_tool",
            scope_id="test_session",
        )

    assert len(executor.written_files) == 0
    error = exc_info.value
    assert error.session_id == "test_session"
    assert error.requested_bytes > 0
    assert error.available_bytes == 100


@pytest.mark.asyncio
async def test_quota_check_with_compression() -> None:
    """Test quota check works correctly with compression enabled."""
    executor = MockExecutor()
    quota_checker = MockQuotaChecker(allow_write=True)

    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=True,
        compression_threshold=1000,
        quota_checker=quota_checker,
    )

    content = "A" * 5000

    await callback(
        content=content,
        tool_name="test_tool",
        scope_id="test_session",
    )

    assert len(executor.written_files) == 3
    assert len(quota_checker.check_calls) == 1
    session_id, write_size = quota_checker.check_calls[0]
    assert session_id == "test_session"
    assert write_size < len(content)


@pytest.mark.asyncio
async def test_no_quota_check_when_checker_not_provided() -> None:
    """Test that quota check is skipped when checker is None."""
    executor = MockExecutor()

    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    await callback(
        content="Test content",
        tool_name="test_tool",
        scope_id="test_session",
    )

    assert len(executor.written_files) == 3


@pytest.mark.asyncio
async def test_offload_records_archive_access_for_lifecycle(
    mock_runtime_side_effects: MockAccessTracker,
) -> None:
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    await callback(
        content="Test content",
        tool_name="test_tool",
        scope_id="test_session",
    )

    assert len(mock_runtime_side_effects.accesses) == 1
    path, session_id = mock_runtime_side_effects.accesses[0]
    assert "/.context/test_session/compacted/sha256/" in path
    assert "test_tool_" in path
    assert session_id == "test_session"


@pytest.mark.asyncio
async def test_content_addressed_offload_reuses_existing_archive() -> None:
    """Identical session-scoped content should return the same archive without quota recheck."""
    executor = MockExecutor()
    quota_checker = MockQuotaChecker(allow_write=True)
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=quota_checker,
    )

    first = await callback(
        content="stable content",
        tool_name="test_tool",
        scope_id="test_session",
    )
    second = await callback(
        content="stable content",
        tool_name="test_tool",
        scope_id="test_session",
    )

    assert first.path == second.path
    assert not first.reused
    assert second.reused
    assert len(executor.written_files) == 3
    assert len(quota_checker.check_calls) == 1


@pytest.mark.asyncio
async def test_content_addressed_offload_does_not_reuse_across_sessions() -> None:
    """Archive reuse must stay scoped to one chat/session directory."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    first = await callback(content="same", tool_name="test_tool", scope_id="chat_a")
    second = await callback(content="same", tool_name="test_tool", scope_id="chat_b")

    assert first.path != second.path
    assert not second.reused
    assert ".context/chat_a/" in first.path
    assert ".context/chat_b/" in second.path


@pytest.mark.asyncio
async def test_content_addressed_offload_requires_scope_id() -> None:
    """Archive offload must not share a default directory for anonymous contexts."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    result = await callback(content="same", tool_name="test_tool", scope_id=None)

    assert not result.succeeded
    assert result.failure_kind == "unsupported"
    assert len(executor.written_files) == 0


@pytest.mark.asyncio
async def test_content_addressed_offload_rewrites_corrupted_archive() -> None:
    """A matching metadata file is insufficient when the archive payload hash differs."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    first = await callback(content="stable content", tool_name="test_tool", scope_id="chat_a")
    executor.written_files[first.path] = "corrupted data"
    second = await callback(content="stable content", tool_name="test_tool", scope_id="chat_a")

    assert first.path == second.path
    assert not second.reused
    assert executor.written_files[first.path] == "stable content"


@pytest.mark.asyncio
async def test_content_addressed_offload_rebuilds_invalid_restore_map_on_reuse() -> None:
    """Retry reuse must self-heal a corrupted restore-map sidecar."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    first = await callback(content="stable content", tool_name="test_tool", scope_id="chat_a")
    restore_map_path = f"{first.path}.restore.json"
    executor.written_files[restore_map_path] = json.dumps(
        {
            "schema_version": 1,
            "archive_path": first.path,
            "line_count": 1,
            "recommended_ranges": [f"{first.path}:2-3"],
        }
    )

    second = await callback(content="stable content", tool_name="test_tool", scope_id="chat_a")

    assert second.reused
    restored_map = json.loads(str(executor.written_files[restore_map_path]))
    assert restored_map["schema_version"] == 2
    assert restored_map["content_index"]["line_count"] == 1
    assert restored_map["recommended_ranges"] == [f"{first.path}:1-1"]


@pytest.mark.asyncio
async def test_content_addressed_offload_rebuilds_schema_v1_restore_map_on_reuse() -> None:
    """Retry reuse must keep the restore-map sidecar on the current schema."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=False,
        quota_checker=None,
    )

    first = await callback(content="stable content", tool_name="test_tool", scope_id="chat_a")
    restore_map_path = f"{first.path}.restore.json"
    executor.written_files[restore_map_path] = json.dumps(
        {
            "schema_version": 1,
            "archive_path": first.path,
            "line_count": 1,
            "recommended_ranges": [f"{first.path}:1-1"],
        }
    )

    second = await callback(content="stable content", tool_name="test_tool", scope_id="chat_a")

    assert second.reused
    restored_map = json.loads(str(executor.written_files[restore_map_path]))
    assert restored_map["schema_version"] == 2
    assert restored_map["content_index"]["line_count"] == 1
    assert restored_map["recommended_ranges"] == [f"{first.path}:1-1"]


@pytest.mark.asyncio
async def test_compressed_archive_restore_map_ranges_reference_uncompressed_lines() -> None:
    """Gzip archives must still provide ranges that recover the original source lines."""
    executor = MockExecutor()
    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=True,
        compression_threshold=1,
        quota_checker=None,
    )
    lines = [f"line {index}" for index in range(1, 260)]
    lines[219] = "ERROR: target failure line"
    content = "\n".join(lines)

    result = await callback(content=content, tool_name="test_tool", scope_id="chat_gzip")

    assert result.path.endswith(".txt.gz")
    stored = executor.written_files[result.path]
    assert isinstance(stored, bytes)
    assert gzip.decompress(stored).decode("utf-8") == content
    restore_map = json.loads(str(executor.written_files[f"{result.path}.restore.json"]))
    assert restore_map["schema_version"] == 2
    assert restore_map["content_index"]["line_count"] == len(lines)
    primary_range = restore_map["recommended_ranges"][0]
    assert primary_range.startswith(f"{result.path}:")
    _, line_range = primary_range.rsplit(":", 1)
    start, end = (int(value) for value in line_range.split("-", 1))
    restored_lines = content.splitlines()[start - 1 : end]
    assert "ERROR: target failure line" in restored_lines


@pytest.mark.asyncio
async def test_compression_failure_then_quota_check() -> None:
    """Test that quota check happens after compression fallback."""
    executor = MockExecutor()
    quota_checker = MockQuotaChecker(allow_write=False, remaining_quota=100)

    callback = create_compress_offload_callback(
        cast(CodeExecutor, executor),
        enable_compression=True,
        compression_threshold=1000,
        quota_checker=quota_checker,
    )

    with patch(
        "myrm_agent_harness.runtime.context.offload.compress_content_async",
        side_effect=RuntimeError("Compression failed"),
    ):
        with pytest.raises(QuotaExceededError):
            await callback(
                content="A" * 5000,
                tool_name="test_tool",
                scope_id="test_session",
            )

        assert len(executor.written_files) == 0
        assert len(quota_checker.check_calls) == 1
        _, write_size = quota_checker.check_calls[0]
        assert write_size >= 5000


@pytest.mark.asyncio
async def test_cleanup_session_context_files_uses_bound_workspace_contract(
    mock_runtime_side_effects: MockAccessTracker,
) -> None:
    executor = MockCleanupExecutor()

    with patch("myrm_agent_harness.runtime.context.cleanup_ops.os.path.isdir", return_value=True):
        await cleanup_session_context_files("session_cleanup", cast(CodeExecutor, executor))

    assert len(executor.executed_contexts) == 1
    context = executor.executed_contexts[0]
    assert context.session_id == "session_cleanup"
    assert context.work_dir == executor.workspace_path
    assert context.workspace_root == executor.workspace_path
    assert "rm -rf" not in context.code
    assert "shutil.rmtree(target)" in context.code
    assert "refusing to remove path outside context root" in context.code
    assert mock_runtime_side_effects.deleted_sessions == ["session_cleanup"]


@pytest.mark.asyncio
async def test_cleanup_session_context_files_skips_when_context_root_missing(
    mock_runtime_side_effects: MockAccessTracker,
) -> None:
    executor = MockCleanupExecutor()

    await cleanup_session_context_files("session_cleanup", cast(CodeExecutor, executor))

    assert len(executor.executed_contexts) == 0
    assert mock_runtime_side_effects.deleted_sessions == []


@pytest.mark.asyncio
async def test_cleanup_session_context_files_skips_empty_chat_id(
    mock_runtime_side_effects: MockAccessTracker,
) -> None:
    executor = MockCleanupExecutor()

    await cleanup_session_context_files("", cast(CodeExecutor, executor))

    assert len(executor.executed_contexts) == 0
