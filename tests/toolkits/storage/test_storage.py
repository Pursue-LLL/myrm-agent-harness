"""Unit tests for storage system."""

import pytest

from tests.mocks import InMemoryStorageBackend


class TestInMemoryStorageBackend:
    """Tests for InMemoryStorageBackend."""

    @pytest.fixture
    def backend(self):
        """Create a clean backend for each test."""
        backend = InMemoryStorageBackend()
        yield backend
        backend.clear()

    @pytest.mark.asyncio
    async def test_write_and_read(self, backend: InMemoryStorageBackend):
        """Test writing and reading a file."""
        content = b"Hello, World!"
        await backend.write("test.txt", content)

        # Read back
        read_content = await backend.read("test.txt")

        assert read_content == content

    @pytest.mark.asyncio
    async def test_read_nonexistent_file_raises_error(self, backend: InMemoryStorageBackend):
        """Test that reading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            await backend.read("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_exists(self, backend: InMemoryStorageBackend):
        """Test checking if file exists."""
        await backend.write("test.txt", b"content")

        assert await backend.exists("test.txt")
        assert not await backend.exists("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_list_all(self, backend: InMemoryStorageBackend):
        """Test listing all files."""
        await backend.write("file1.txt", b"content1")
        await backend.write("file2.txt", b"content2")
        await backend.write("dir/file3.txt", b"content3")

        # List all
        files = await backend.list()

        assert len(files) == 3
        assert "file1.txt" in files
        assert "file2.txt" in files
        assert "dir/file3.txt" in files

    @pytest.mark.asyncio
    async def test_list_with_prefix(self, backend: InMemoryStorageBackend):
        """Test listing files with prefix filter."""
        await backend.write("dir1/file1.txt", b"content1")
        await backend.write("dir1/file2.txt", b"content2")
        await backend.write("dir2/file3.txt", b"content3")

        # List with prefix
        files = await backend.list("dir1/")

        assert len(files) == 2
        assert "dir1/file1.txt" in files
        assert "dir1/file2.txt" in files
        assert "dir2/file3.txt" not in files

    @pytest.mark.asyncio
    async def test_delete(self, backend: InMemoryStorageBackend):
        """Test deleting a file."""
        await backend.write("test.txt", b"content")

        # Delete
        await backend.delete("test.txt")

        assert not await backend.exists("test.txt")

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file_raises_error(self, backend: InMemoryStorageBackend):
        """Test that deleting nonexistent file raises error."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            await backend.delete("nonexistent.txt")

    @pytest.mark.asyncio
    async def test_overwrite_file(self, backend: InMemoryStorageBackend):
        """Test overwriting an existing file."""
        await backend.write("test.txt", b"old content")
        await backend.write("test.txt", b"new content")

        # Read back
        content = await backend.read("test.txt")

        assert content == b"new content"
