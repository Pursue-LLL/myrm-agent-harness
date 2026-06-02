"""Tests for PersistentStorageBackend.

Covers routing logic, all 11 StorageProvider methods, idempotent delete, and path security.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.storage.base import StorageError
from myrm_agent_harness.toolkits.storage.persistent import (
    PERSISTENT_PREFIXES,
    PersistentStorageBackend,
)


@pytest.fixture
def storage(tmp_path: Path) -> PersistentStorageBackend:
    persistent = tmp_path / "persistent"
    workspace = tmp_path / "workspace"
    return PersistentStorageBackend(
        persistent_path=str(persistent),
        workspace_path=str(workspace),
    )


@pytest.fixture
def ns_storage(tmp_path: Path) -> PersistentStorageBackend:
    persistent = tmp_path / "persistent"
    workspace = tmp_path / "workspace"
    return PersistentStorageBackend(
        persistent_path=str(persistent),
        workspace_path=str(workspace),
        namespace="user_alice",
    )


class TestRouting:
    @pytest.mark.asyncio
    async def test_artifacts_route_to_persistent(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/report.pdf", b"pdf_data")
        path, is_persistent = storage._route_path("artifacts/report.pdf")
        assert is_persistent is True
        assert "persistent" in str(path)

    @pytest.mark.asyncio
    async def test_regular_files_route_to_workspace(self, storage: PersistentStorageBackend) -> None:
        await storage.write("temp/scratch.txt", b"temp_data")
        path, is_persistent = storage._route_path("temp/scratch.txt")
        assert is_persistent is False
        assert "workspace" in str(path)

    def test_all_persistent_prefixes(self, storage: PersistentStorageBackend) -> None:
        for prefix in PERSISTENT_PREFIXES:
            _, is_persistent = storage._route_path(f"{prefix}test.txt")
            assert is_persistent is True, f"Expected {prefix} to route to persistent"


class TestReadWrite:
    @pytest.mark.asyncio
    async def test_write_and_read(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/data.bin", b"\x00\x01\x02")
        assert await storage.read("artifacts/data.bin") == b"\x00\x01\x02"

    @pytest.mark.asyncio
    async def test_write_text_and_read_text(self, storage: PersistentStorageBackend) -> None:
        await storage.write_text("artifacts/readme.md", "# Hello")
        assert await storage.read_text("artifacts/readme.md") == "# Hello"

    @pytest.mark.asyncio
    async def test_workspace_read_write(self, storage: PersistentStorageBackend) -> None:
        await storage.write("temp/file.txt", b"workspace data")
        assert await storage.read("temp/file.txt") == b"workspace data"

    @pytest.mark.asyncio
    async def test_read_nonexistent_raises(self, storage: PersistentStorageBackend) -> None:
        with pytest.raises(FileNotFoundError, match="File not found"):
            await storage.read("artifacts/missing.txt")


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_file(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/to_delete.txt", b"content")
        await storage.delete("artifacts/to_delete.txt")
        assert not await storage.exists("artifacts/to_delete.txt")

    @pytest.mark.asyncio
    async def test_delete_idempotent(self, storage: PersistentStorageBackend) -> None:
        """Deleting a nonexistent file should not raise (idempotent)."""
        await storage.delete("nonexistent.txt")


class TestExists:
    @pytest.mark.asyncio
    async def test_exists_true(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/present.txt", b"here")
        assert await storage.exists("artifacts/present.txt") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, storage: PersistentStorageBackend) -> None:
        assert await storage.exists("artifacts/absent.txt") is False

    @pytest.mark.asyncio
    async def test_exists_path_traversal_returns_false(self, storage: PersistentStorageBackend) -> None:
        assert await storage.exists("../../etc/passwd") is False


class TestList:
    @pytest.mark.asyncio
    async def test_list_merges_volumes(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/a.txt", b"a")
        await storage.write("temp/b.txt", b"b")

        files = await storage.list()
        assert len(files) >= 2

    @pytest.mark.asyncio
    async def test_list_empty(self, storage: PersistentStorageBackend) -> None:
        files = await storage.list()
        assert files == []


class TestInfo:
    @pytest.mark.asyncio
    async def test_info(self, storage: PersistentStorageBackend) -> None:
        content = b"test content"
        await storage.write("artifacts/info.txt", content)
        info = await storage.info("artifacts/info.txt")

        assert info.key == "artifacts/info.txt"
        assert info.size == len(content)
        assert info.last_modified is not None
        assert info.last_modified.tzinfo is not None

    @pytest.mark.asyncio
    async def test_info_nonexistent_raises(self, storage: PersistentStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.info("artifacts/missing.txt")


class TestCopyMove:
    @pytest.mark.asyncio
    async def test_copy(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/src.txt", b"content")
        await storage.copy("artifacts/src.txt", "artifacts/dst.txt")

        assert await storage.read("artifacts/src.txt") == b"content"
        assert await storage.read("artifacts/dst.txt") == b"content"

    @pytest.mark.asyncio
    async def test_copy_nonexistent_raises(self, storage: PersistentStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.copy("missing.txt", "dst.txt")

    @pytest.mark.asyncio
    async def test_move(self, storage: PersistentStorageBackend) -> None:
        await storage.write("temp/src.txt", b"content")
        await storage.move("temp/src.txt", "temp/dst.txt")

        assert not await storage.exists("temp/src.txt")
        assert await storage.read("temp/dst.txt") == b"content"

    @pytest.mark.asyncio
    async def test_move_nonexistent_raises(self, storage: PersistentStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.move("missing.txt", "dst.txt")


class TestGetUrl:
    @pytest.mark.asyncio
    async def test_get_url(self, storage: PersistentStorageBackend) -> None:
        await storage.write("artifacts/file.txt", b"content")
        url = await storage.get_url("artifacts/file.txt")
        assert url.startswith("file://")

    @pytest.mark.asyncio
    async def test_get_url_nonexistent_raises(self, storage: PersistentStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.get_url("missing.txt")


class TestPathSecurity:
    def test_path_traversal_blocked(self, storage: PersistentStorageBackend) -> None:
        with pytest.raises(StorageError, match="Path traversal"):
            storage._route_path("../../etc/passwd")


class TestNamespace:
    @pytest.mark.asyncio
    async def test_namespace_write_read(self, ns_storage: PersistentStorageBackend) -> None:
        await ns_storage.write("artifacts/config.json", b'{"key": "value"}')
        assert await ns_storage.read("artifacts/config.json") == b'{"key": "value"}'

    @pytest.mark.asyncio
    async def test_namespace_routing(self, ns_storage: PersistentStorageBackend) -> None:
        """With namespace 'user_alice', key 'temp/test.txt' becomes 'user_alice/temp/test.txt' (workspace)."""
        path, is_persistent = ns_storage._route_path("temp/test.txt")
        assert is_persistent is False
        assert "user_alice" in str(path)
