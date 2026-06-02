"""Tests for transparent file reader."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.transparent_reader import (
    TransparentFileReader,
    read_context_file_async,
    read_context_file_sync,
)


@pytest.fixture
def test_files(tmp_path: Path) -> tuple[Path, Path]:
    """Create test files (plain and compressed)."""
    plain_file = tmp_path / "test.txt"
    gz_file = tmp_path / "test.txt.gz"

    content = "This is test content\nLine 2\nLine 3"
    plain_file.write_text(content, encoding="utf-8")

    with gzip.open(gz_file, "wt", encoding="utf-8") as f:
        f.write(content)

    return plain_file, gz_file


def test_read_plain_file_sync(test_files: tuple[Path, Path]) -> None:
    """Test reading plain text file synchronously."""
    plain_file, _ = test_files

    content = read_context_file_sync(plain_file)

    assert content == "This is test content\nLine 2\nLine 3"


def test_read_compressed_file_sync(test_files: tuple[Path, Path]) -> None:
    """Test reading compressed file synchronously."""
    _, gz_file = test_files

    content = read_context_file_sync(gz_file)

    assert content == "This is test content\nLine 2\nLine 3"


@pytest.mark.asyncio
async def test_read_plain_file_async(test_files: tuple[Path, Path]) -> None:
    """Test reading plain text file asynchronously."""
    plain_file, _ = test_files

    content = await read_context_file_async(plain_file)

    assert content == "This is test content\nLine 2\nLine 3"


@pytest.mark.asyncio
async def test_read_compressed_file_async(test_files: tuple[Path, Path]) -> None:
    """Test reading compressed file asynchronously."""
    _, gz_file = test_files

    content = await read_context_file_async(gz_file)

    assert content == "This is test content\nLine 2\nLine 3"


def test_read_nonexistent_file_sync(tmp_path: Path) -> None:
    """Test reading non-existent file raises FileNotFoundError."""
    nonexistent = tmp_path / "nonexistent.txt"

    with pytest.raises(FileNotFoundError):
        read_context_file_sync(nonexistent)


@pytest.mark.asyncio
async def test_read_nonexistent_file_async(tmp_path: Path) -> None:
    """Test reading non-existent file raises FileNotFoundError."""
    nonexistent = tmp_path / "nonexistent.txt"

    with pytest.raises(FileNotFoundError):
        await read_context_file_async(nonexistent)


def test_transparent_reader_is_compressed(tmp_path: Path) -> None:
    """Test compression detection."""
    reader = TransparentFileReader()

    plain_file = tmp_path / "test.txt"
    gz_file = tmp_path / "test.txt.gz"

    assert reader.is_compressed(gz_file) is True
    assert reader.is_compressed(plain_file) is False


@pytest.mark.asyncio
async def test_transparent_reader_async(test_files: tuple[Path, Path]) -> None:
    """Test TransparentFileReader async interface."""
    plain_file, gz_file = test_files
    reader = TransparentFileReader()

    plain_content = await reader.read_async(plain_file)
    gz_content = await reader.read_async(gz_file)

    assert plain_content == gz_content
    assert "This is test content" in plain_content


def test_transparent_reader_sync(test_files: tuple[Path, Path]) -> None:
    """Test TransparentFileReader sync interface."""
    plain_file, gz_file = test_files
    reader = TransparentFileReader()

    plain_content = reader.read_sync(plain_file)
    gz_content = reader.read_sync(gz_file)

    assert plain_content == gz_content
    assert "This is test content" in plain_content


@pytest.mark.asyncio
async def test_large_file_decompression(tmp_path: Path) -> None:
    """Test decompression of large files."""
    gz_file = tmp_path / "large.txt.gz"
    large_content = "Line content\n" * 10000

    with gzip.open(gz_file, "wt", encoding="utf-8") as f:
        f.write(large_content)

    content = await read_context_file_async(gz_file)

    assert len(content) == len(large_content)
    assert content.count("\n") == 10000
