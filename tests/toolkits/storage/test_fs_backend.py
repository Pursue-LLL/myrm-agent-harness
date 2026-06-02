"""Tests for BaseFileSystemBackend base class.

Covers base class specific logic: errno translation, IsADirectoryError handling,
and Path.as_uri() URL encoding. General CRUD is tested via LocalStorageBackend.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.storage._fs_backend import BaseFileSystemBackend
from myrm_agent_harness.toolkits.storage.base import StorageError
from myrm_agent_harness.toolkits.storage.local import LocalStorageBackend


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorageBackend:
    return LocalStorageBackend(tmp_path)


class TestTranslateOsError:
    """Test _translate_os_error static method."""

    def test_enospc(self) -> None:
        err = OSError(errno.ENOSPC, "No space")
        result = BaseFileSystemBackend._translate_os_error(err, "test.txt")
        assert isinstance(result, OSError)
        assert "No space left on device" in str(result)

    def test_enametoolong(self) -> None:
        err = OSError(errno.ENAMETOOLONG, "Name too long")
        result = BaseFileSystemBackend._translate_os_error(err, "test.txt")
        assert isinstance(result, ValueError)
        assert "File name too long" in str(result)

    def test_erofs(self) -> None:
        err = OSError(errno.EROFS, "Read-only FS")
        result = BaseFileSystemBackend._translate_os_error(err, "test.txt")
        assert isinstance(result, PermissionError)
        assert "Read-only file system" in str(result)

    def test_generic_oserror(self) -> None:
        err = OSError(errno.EIO, "I/O error")
        result = BaseFileSystemBackend._translate_os_error(err, "test.txt")
        assert isinstance(result, StorageError)
        assert "Failed to write" in str(result)


class TestReadDirectoryError:
    """Test that reading a directory raises StorageError."""

    @pytest.mark.asyncio
    async def test_read_directory_raises_storage_error(self, storage: LocalStorageBackend) -> None:
        dir_key = "some_dir"
        dir_path = storage.base_path / dir_key
        dir_path.mkdir(parents=True)

        with pytest.raises(StorageError, match="Not a file"):
            await storage.read(dir_key)


class TestGetUrlEncoding:
    """Test that get_url properly encodes special characters."""

    @pytest.mark.asyncio
    async def test_url_encodes_spaces(self, storage: LocalStorageBackend) -> None:
        key = "path with spaces/file name.txt"
        await storage.write(key, b"content")
        url = await storage.get_url(key)
        assert url.startswith("file:///")
        assert "%20" in url or "+" in url

    @pytest.mark.asyncio
    async def test_url_encodes_unicode(self, storage: LocalStorageBackend) -> None:
        key = "目录/文件.txt"
        await storage.write(key, b"content")
        url = await storage.get_url(key)
        assert url.startswith("file:///")
        assert "%" in url


class TestWriteTextErrnoHandling:
    """Test that write_text also uses errno translation."""

    @pytest.mark.asyncio
    async def test_write_text_to_readonly_dir(self, tmp_path: Path) -> None:
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        (readonly_dir / "existing.txt").write_text("x")

        backend = LocalStorageBackend(readonly_dir)

        os.chmod(str(readonly_dir), 0o444)
        try:
            with pytest.raises((PermissionError, StorageError, OSError)):
                await backend.write_text("subdir/new.txt", "content")
        finally:
            os.chmod(str(readonly_dir), 0o755)


class TestInfoTryExcept:
    """Test that info uses try/except instead of exists check."""

    @pytest.mark.asyncio
    async def test_info_nonexistent_key(self, storage: LocalStorageBackend) -> None:
        with pytest.raises(FileNotFoundError, match="File not found"):
            await storage.info("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_info_returns_correct_size(self, storage: LocalStorageBackend) -> None:
        content = b"hello world"
        await storage.write("sized.txt", content)
        file_info = await storage.info("sized.txt")
        assert file_info.size == len(content)
        assert file_info.content_type == "text/plain"
