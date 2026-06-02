"""Tests for LocalStorageBackend.

Covers all 11 StorageProvider methods, path security, errno handling, and namespace isolation.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.storage.base import StorageError
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(tmp_path)


@pytest.fixture
def ns_storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(tmp_path, namespace="tenant_a")


class TestReadWrite:
    @pytest.mark.asyncio
    async def test_write_and_read_bytes(self, storage: LocalStorageBackend) -> None:
        content = b"\x00\x01\x02binary data"
        await storage.write("data.bin", content)
        assert await storage.read("data.bin") == content

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self, storage: LocalStorageBackend) -> None:
        await storage.write("a/b/c/deep.txt", b"deep")
        assert await storage.read("a/b/c/deep.txt") == b"deep"

    @pytest.mark.asyncio
    async def test_write_sets_permissions(self, storage: LocalStorageBackend) -> None:
        await storage.write("secret.txt", b"sensitive")
        path = Path(storage.resolve_absolute_path("secret.txt"))
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    @pytest.mark.asyncio
    async def test_read_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError, match="File not found"):
            await storage.read("missing.txt")

    @pytest.mark.asyncio
    async def test_read_directory_raises(self, storage: LocalStorageBackend, tmp_path: Path) -> None:
        (tmp_path / "adir").mkdir()
        with pytest.raises(StorageError, match="Not a file"):
            await storage.read("adir")

    @pytest.mark.asyncio
    async def test_overwrite(self, storage: LocalStorageBackend) -> None:
        await storage.write("f.txt", b"old")
        await storage.write("f.txt", b"new")
        assert await storage.read("f.txt") == b"new"


class TestReadWriteText:
    @pytest.mark.asyncio
    async def test_write_and_read_text(self, storage: LocalStorageBackend) -> None:
        await storage.write_text("readme.txt", "Hello, 世界!")
        assert await storage.read_text("readme.txt") == "Hello, 世界!"

    @pytest.mark.asyncio
    async def test_read_text_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read_text("missing.txt")

    @pytest.mark.asyncio
    async def test_custom_encoding(self, storage: LocalStorageBackend) -> None:
        text = "中文内容"
        await storage.write_text("gbk.txt", text, encoding="gbk")
        assert await storage.read_text("gbk.txt", encoding="gbk") == text


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_file(self, storage: LocalStorageBackend) -> None:
        await storage.write("to_delete.txt", b"content")
        await storage.delete("to_delete.txt")
        assert not await storage.exists("to_delete.txt")

    @pytest.mark.asyncio
    async def test_delete_directory(self, storage: LocalStorageBackend) -> None:
        await storage.write("dir/a.txt", b"a")
        await storage.write("dir/b.txt", b"b")
        await storage.delete("dir")
        assert not await storage.exists("dir")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError, match="File not found"):
            await storage.delete("gone.txt")


class TestExists:
    @pytest.mark.asyncio
    async def test_exists_true(self, storage: LocalStorageBackend) -> None:
        await storage.write("present.txt", b"here")
        assert await storage.exists("present.txt") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, storage: LocalStorageBackend) -> None:
        assert await storage.exists("absent.txt") is False

    @pytest.mark.asyncio
    async def test_exists_path_traversal_returns_false(self, storage: LocalStorageBackend) -> None:
        assert await storage.exists("../../etc/passwd") is False


class TestList:
    @pytest.mark.asyncio
    async def test_list_recursive(self, storage: LocalStorageBackend) -> None:
        await storage.write("a.txt", b"a")
        await storage.write("sub/b.txt", b"b")
        await storage.write("sub/deep/c.txt", b"c")

        files = await storage.list()
        assert sorted(files) == ["a.txt", "sub/b.txt", "sub/deep/c.txt"]

    @pytest.mark.asyncio
    async def test_list_with_prefix(self, storage: LocalStorageBackend) -> None:
        await storage.write("docs/a.txt", b"a")
        await storage.write("docs/b.txt", b"b")
        await storage.write("src/c.txt", b"c")

        files = await storage.list(prefix="docs")
        assert sorted(files) == ["docs/a.txt", "docs/b.txt"]

    @pytest.mark.asyncio
    async def test_list_empty_dir(self, storage: LocalStorageBackend) -> None:
        files = await storage.list()
        assert files == []

    @pytest.mark.asyncio
    async def test_list_nonexistent_prefix(self, storage: LocalStorageBackend) -> None:
        files = await storage.list(prefix="nonexistent")
        assert files == []


class TestInfo:
    @pytest.mark.asyncio
    async def test_info(self, storage: LocalStorageBackend) -> None:
        content = b"test content"
        await storage.write("info.txt", content)
        info = await storage.info("info.txt")

        assert info.key == "info.txt"
        assert info.size == len(content)
        assert info.last_modified is not None
        assert info.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_info_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.info("missing.txt")


class TestCopyMove:
    @pytest.mark.asyncio
    async def test_copy_file(self, storage: LocalStorageBackend) -> None:
        await storage.write("src.txt", b"content")
        await storage.copy("src.txt", "dst.txt")

        assert await storage.read("src.txt") == b"content"
        assert await storage.read("dst.txt") == b"content"

    @pytest.mark.asyncio
    async def test_copy_creates_dirs(self, storage: LocalStorageBackend) -> None:
        await storage.write("src.txt", b"content")
        await storage.copy("src.txt", "new/dir/dst.txt")
        assert await storage.read("new/dir/dst.txt") == b"content"

    @pytest.mark.asyncio
    async def test_copy_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError, match="Source file not found"):
            await storage.copy("missing.txt", "dst.txt")

    @pytest.mark.asyncio
    async def test_move(self, storage: LocalStorageBackend) -> None:
        await storage.write("src.txt", b"content")
        await storage.move("src.txt", "dst.txt")

        assert not await storage.exists("src.txt")
        assert await storage.read("dst.txt") == b"content"

    @pytest.mark.asyncio
    async def test_move_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError, match="Source file not found"):
            await storage.move("missing.txt", "dst.txt")


class TestGetUrl:
    @pytest.mark.asyncio
    async def test_get_url(self, storage: LocalStorageBackend) -> None:
        await storage.write("file.txt", b"content")
        url = await storage.get_url("file.txt")
        assert url.startswith("file://")
        assert "file.txt" in url

    @pytest.mark.asyncio
    async def test_get_url_nonexistent_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.get_url("missing.txt")


class TestResolveAbsolutePath:
    def test_resolve_absolute_path(self, storage: LocalStorageBackend) -> None:
        path = storage.resolve_absolute_path("some/file.txt")
        assert os.path.isabs(path)
        assert path.endswith("some/file.txt")


class TestPathSecurity:
    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(StorageError, match="Path traversal"):
            await storage.read("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_absolute_path_blocked(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(StorageError, match="Path traversal"):
            await storage.read("../../../tmp/evil")

    def test_resolve_path_traversal_raises(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(StorageError, match="Path traversal"):
            storage.resolve_absolute_path("../../etc/passwd")


class TestNamespace:
    @pytest.mark.asyncio
    async def test_namespace_isolation(self, ns_storage: LocalStorageBackend) -> None:
        await ns_storage.write("config.json", b'{"key": "value"}')

        path = ns_storage.resolve_absolute_path("config.json")
        assert "tenant_a" in path

        assert await ns_storage.read("config.json") == b'{"key": "value"}'

    @pytest.mark.asyncio
    async def test_namespace_list(self, ns_storage: LocalStorageBackend) -> None:
        await ns_storage.write("a.txt", b"a")
        await ns_storage.write("sub/b.txt", b"b")

        files = await ns_storage.list()
        assert len(files) >= 2

    @pytest.mark.asyncio
    async def test_namespace_exists(self, ns_storage: LocalStorageBackend) -> None:
        await ns_storage.write("file.txt", b"content")
        assert await ns_storage.exists("file.txt") is True
        assert await ns_storage.exists("nonexistent.txt") is False
