"""Tests for CodeExecutor compression/decompression integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.compression import compress_content
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor


class TestExecutorCompression:
    """Test CodeExecutor with compressed files."""

    @pytest.fixture
    async def executor(self, tmp_path: Path) -> LocalExecutor:
        """Create LocalExecutor with temp workspace."""
        workspace = tmp_path / "workspace"
        workspace.mkdir()

        config = ExecutionConfig()
        executor = LocalExecutor(config, workspace_path=str(workspace))
        return executor

    @pytest.mark.asyncio
    async def test_read_compressed_file(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test reading gzip-compressed file."""
        # Create compressed file
        content = "Hello World from compressed file" * 100
        compressed = compress_content(content)

        file_path = tmp_path / "workspace" / "test.txt.gz"
        file_path.write_bytes(compressed)

        # Read should auto-decompress
        result = await executor.read_file("test.txt.gz")
        assert result == content

    @pytest.mark.asyncio
    async def test_read_uncompressed_file(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test reading regular text file."""
        content = "Hello World from text file"

        file_path = tmp_path / "workspace" / "test.txt"
        file_path.write_text(content)

        # Read should work normally
        result = await executor.read_file("test.txt")
        assert result == content

    @pytest.mark.asyncio
    async def test_read_compressed_context_file(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test reading compressed context offload file."""
        # Create context directory structure
        context_dir = tmp_path / "workspace" / ".context" / "session1" / "compacted"
        context_dir.mkdir(parents=True)

        # Create compressed context file
        content = "<html><body>Large search result</body></html>" * 500
        compressed = compress_content(content)

        file_path = context_dir / "web_search_abc123.txt.gz"
        file_path.write_bytes(compressed)

        # Read should auto-decompress
        result = await executor.read_file(".context/session1/compacted/web_search_abc123.txt.gz")
        assert result == content

    @pytest.mark.asyncio
    async def test_read_invalid_gzip_file(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test reading invalid gzip file raises error."""
        # Create file with .gz extension but invalid content
        file_path = tmp_path / "workspace" / "invalid.txt.gz"
        file_path.write_bytes(b"not gzip data")

        # Should raise error
        with pytest.raises(Exception):
            await executor.read_file("invalid.txt.gz")

    @pytest.mark.asyncio
    async def test_write_and_read_compressed_roundtrip(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test full write-compress-read-decompress roundtrip."""
        # Write compressed file
        content = "Test content for roundtrip" * 200
        compressed = compress_content(content)

        await executor.write_file_bytes("roundtrip.txt.gz", compressed)

        # Read should auto-decompress
        result = await executor.read_file("roundtrip.txt.gz")
        assert result == content

    @pytest.mark.asyncio
    async def test_mixed_compressed_uncompressed_files(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test reading both compressed and uncompressed files."""
        # Create uncompressed file
        content1 = "Uncompressed content"
        await executor.write_file("file1.txt", content1)

        # Create compressed file
        content2 = "Compressed content" * 100
        compressed = compress_content(content2)
        await executor.write_file_bytes("file2.txt.gz", compressed)

        # Read both
        result1 = await executor.read_file("file1.txt")
        result2 = await executor.read_file("file2.txt.gz")

        assert result1 == content1
        assert result2 == content2

    @pytest.mark.asyncio
    async def test_large_compressed_file(self, executor: LocalExecutor, tmp_path: Path) -> None:
        """Test reading large compressed file."""
        # Create large content (1MB)
        content = "A" * (1024 * 1024)
        compressed = compress_content(content)

        file_path = tmp_path / "workspace" / "large.txt.gz"
        file_path.write_bytes(compressed)

        # Read should handle large files
        result = await executor.read_file("large.txt.gz")
        assert result == content
        assert len(result) == 1024 * 1024
