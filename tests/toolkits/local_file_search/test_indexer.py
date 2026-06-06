"""Unit tests for local_file_search.indexer."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from myrm_agent_harness.toolkits.local_file_search.config import (
    LocalFileSearchConfig,
)
from myrm_agent_harness.toolkits.local_file_search.indexer import (
    LocalFileIndexer,
    _compute_file_hash,
    _parse_file_content,
    _scan_directory,
)
from myrm_agent_harness.toolkits.local_file_search.models import (
    FileRecord,
    IndexedDirectory,
    IndexStatus,
)


class TestComputeFileHash:
    def test_hash_consistency(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h1 = _compute_file_hash(str(f))
        h2 = _compute_file_hash(str(f))
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex digest

    def test_different_content_different_hash(self, tmp_path: Path):
        f1 = tmp_path / "a.txt"
        f1.write_text("content A")
        f2 = tmp_path / "b.txt"
        f2.write_text("content B")
        assert _compute_file_hash(str(f1)) != _compute_file_hash(str(f2))


class TestScanDirectory:
    def test_scan_basic(self, tmp_path: Path):
        (tmp_path / "doc.txt").write_text("hello")
        (tmp_path / "code.py").write_text("print(1)")
        (tmp_path / "image.png").write_bytes(b"\x89PNG")  # unsupported

        d = IndexedDirectory(path=str(tmp_path))
        result = _scan_directory(d, frozenset(), 1024 * 1024)
        paths = [os.path.basename(p) for p in result]
        assert "doc.txt" in paths
        assert "code.py" in paths
        assert "image.png" not in paths

    def test_scan_excludes_dirs(self, tmp_path: Path):
        sub = tmp_path / "node_modules"
        sub.mkdir()
        (sub / "index.js").write_text("module.exports = {}")
        (tmp_path / "app.js").write_text("console.log('hi')")

        d = IndexedDirectory(path=str(tmp_path))
        result = _scan_directory(d, frozenset({"node_modules"}), 10 * 1024 * 1024)
        paths = [os.path.basename(p) for p in result]
        assert "app.js" in paths
        assert "index.js" not in paths

    def test_scan_excludes_hidden_dirs(self, tmp_path: Path):
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "secret.txt").write_text("secret")
        (tmp_path / "visible.txt").write_text("hello")

        d = IndexedDirectory(path=str(tmp_path))
        result = _scan_directory(d, frozenset(), 10 * 1024 * 1024)
        paths = [os.path.basename(p) for p in result]
        assert "visible.txt" in paths
        assert "secret.txt" not in paths

    def test_scan_excludes_hidden_files(self, tmp_path: Path):
        (tmp_path / ".gitignore").write_text("*.pyc")
        (tmp_path / "readme.md").write_text("# README")

        d = IndexedDirectory(path=str(tmp_path))
        result = _scan_directory(d, frozenset(), 10 * 1024 * 1024)
        paths = [os.path.basename(p) for p in result]
        assert "readme.md" in paths
        assert ".gitignore" not in paths

    def test_scan_respects_max_file_size(self, tmp_path: Path):
        small = tmp_path / "small.txt"
        small.write_text("small")
        big = tmp_path / "big.txt"
        big.write_text("x" * 200)

        d = IndexedDirectory(path=str(tmp_path))
        result = _scan_directory(d, frozenset(), 100)
        paths = [os.path.basename(p) for p in result]
        assert "small.txt" in paths
        assert "big.txt" not in paths

    def test_scan_non_recursive(self, tmp_path: Path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")
        (tmp_path / "top.txt").write_text("top")

        d = IndexedDirectory(path=str(tmp_path), recursive=False)
        result = _scan_directory(d, frozenset(), 10 * 1024 * 1024)
        paths = [os.path.basename(p) for p in result]
        assert "top.txt" in paths
        assert "deep.txt" not in paths

    def test_scan_recursive(self, tmp_path: Path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "deep.txt").write_text("deep")
        (tmp_path / "top.txt").write_text("top")

        d = IndexedDirectory(path=str(tmp_path), recursive=True)
        result = _scan_directory(d, frozenset(), 10 * 1024 * 1024)
        paths = [os.path.basename(p) for p in result]
        assert "top.txt" in paths
        assert "deep.txt" in paths

    def test_scan_nonexistent_dir(self):
        d = IndexedDirectory(path="/nonexistent/path/12345")
        result = _scan_directory(d, frozenset(), 10 * 1024 * 1024)
        assert result == []


@pytest.mark.asyncio
class TestParseFileContent:
    async def test_parse_text_file(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("Hello, this is a test document.")
        result = await _parse_file_content(str(f))
        assert result is not None
        assert "Hello" in result

    async def test_parse_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = await _parse_file_content(str(f))
        assert result is None

    async def test_parse_whitespace_only(self, tmp_path: Path):
        f = tmp_path / "ws.txt"
        f.write_text("   \n\n   ")
        result = await _parse_file_content(str(f))
        assert result is None

    async def test_parse_python_file(self, tmp_path: Path):
        f = tmp_path / "code.py"
        f.write_text("def hello():\n    return 'world'")
        result = await _parse_file_content(str(f))
        assert result is not None
        assert "def hello" in result

    async def test_parse_unsupported_extension(self, tmp_path: Path):
        f = tmp_path / "image.bmp"
        f.write_bytes(b"\x42\x4d")
        result = await _parse_file_content(str(f))
        assert result is None


REALISTIC_TEXT = (
    "# Quarterly Financial Report Q4 2025\n\n"
    "## Executive Summary\n\n"
    "This report presents the financial performance of our organization during the fourth quarter "
    "of fiscal year 2025. Revenue grew by 15.3% year-over-year, reaching $42.7 million, driven "
    "primarily by strong demand in our enterprise software segment. Operating expenses remained "
    "well-controlled at $28.1 million, resulting in an operating margin of 34.2%. Net income for "
    "the quarter was $11.8 million, representing a 22% increase compared to Q4 2024.\n\n"
    "## Key Metrics\n\n"
    "- Annual Recurring Revenue (ARR): $168.5M (+18% YoY)\n"
    "- Customer Retention Rate: 96.2%\n"
    "- Net Promoter Score: 72\n"
    "- Employee Headcount: 1,247 (+89 net new hires)\n\n"
    "## Revenue Breakdown\n\n"
    "Enterprise segment contributed $31.2M (73% of total), while the SMB segment accounted for "
    "$11.5M (27%). International markets grew fastest at 24% YoY, now representing 35% of total "
    "revenue. The APAC region showed particular strength with a 31% growth rate.\n\n"
    "## Looking Ahead\n\n"
    "We expect continued momentum in Q1 2026, with guidance of $44-46M in revenue. Key "
    "initiatives include the launch of our AI-powered analytics platform and expansion into "
    "three new geographic markets. We remain committed to sustainable growth and innovation.\n"
)


@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.collection_exists = AsyncMock(return_value=True)
    store.create_collection = AsyncMock(return_value=True)
    store.upsert = AsyncMock(return_value=[])
    store.delete_by_filter = AsyncMock(return_value=0)
    return store


@pytest.fixture
def mock_embedding_service():
    service = AsyncMock()
    service.embed = AsyncMock(return_value=[0.1] * 1536)
    service.embed_batch = AsyncMock(
        side_effect=lambda texts: [[0.1] * 1536 for _ in texts]
    )
    service.dimension = 1536
    return service


@pytest.fixture
def indexer_config(tmp_path: Path):
    real_path = str(tmp_path.resolve())
    d = IndexedDirectory(id="d1", path=real_path, enabled=True)
    return LocalFileSearchConfig(directories=[d])


@pytest.fixture
def indexer(mock_vector_store, mock_embedding_service, indexer_config):
    return LocalFileIndexer(
        vector_store=mock_vector_store,
        embedding_service=mock_embedding_service,
        config=indexer_config,
    )


@pytest.mark.asyncio
class TestLocalFileIndexer:
    async def test_ensure_collection_creates_when_missing(self, indexer, mock_vector_store):
        mock_vector_store.collection_exists.return_value = False
        await indexer.ensure_collection()
        mock_vector_store.create_collection.assert_called_once()

    async def test_ensure_collection_skips_when_exists(self, indexer, mock_vector_store):
        from myrm_agent_harness.toolkits.vector.base import CollectionInfo

        mock_vector_store.collection_exists.return_value = True
        mock_vector_store.get_collection_info.return_value = CollectionInfo(
            name="local_file_search", dimension=1536, count=0,
        )
        await indexer.ensure_collection()
        mock_vector_store.create_collection.assert_not_called()

    async def test_ensure_collection_recreates_on_dimension_mismatch(self, indexer, mock_vector_store):
        from myrm_agent_harness.toolkits.vector.base import CollectionInfo

        mock_vector_store.collection_exists.return_value = True
        mock_vector_store.get_collection_info.return_value = CollectionInfo(
            name="local_file_search", dimension=768, count=5,
        )
        await indexer.ensure_collection()
        mock_vector_store.delete_collection.assert_called_once_with("local_file_search")
        mock_vector_store.create_collection.assert_called_once()

    async def test_index_all_empty_config(self, mock_vector_store, mock_embedding_service):
        empty_config = LocalFileSearchConfig(directories=[])
        idx = LocalFileIndexer(mock_vector_store, mock_embedding_service, empty_config)
        stats = await idx.index_all()
        assert stats.status == IndexStatus.IDLE

    async def test_index_all_indexes_files(self, indexer, tmp_path, mock_embedding_service):
        (tmp_path / "doc.md").write_text(REALISTIC_TEXT)
        mock_embedding_service.embed_batch.return_value = [[0.1] * 1536]

        stats = await indexer.index_all()
        assert stats.total_files == 1
        assert stats.total_chunks >= 1
        assert stats.status == IndexStatus.IDLE

    async def test_index_all_incremental(self, indexer, tmp_path, mock_embedding_service):
        (tmp_path / "doc.md").write_text(REALISTIC_TEXT)
        mock_embedding_service.embed_batch.return_value = [[0.1] * 1536]

        await indexer.index_all()
        first_call_count = mock_embedding_service.embed_batch.call_count

        stats = await indexer.index_all()
        assert mock_embedding_service.embed_batch.call_count == first_call_count
        assert stats.total_files == 1

    async def test_index_all_detects_changes(self, indexer, tmp_path, mock_embedding_service):
        f = tmp_path / "doc.md"
        f.write_text(REALISTIC_TEXT)
        mock_embedding_service.embed_batch.return_value = [[0.1] * 1536]

        await indexer.index_all()
        first_count = mock_embedding_service.embed_batch.call_count

        f.write_text(REALISTIC_TEXT + "\n## Updated Section\n\nNew analysis data added for verification.")
        await indexer.index_all()
        assert mock_embedding_service.embed_batch.call_count > first_count

    async def test_index_all_removes_stale(self, mock_vector_store, mock_embedding_service):
        with tempfile.TemporaryDirectory() as raw_dir:
            real_dir = str(Path(raw_dir).resolve())
            d = IndexedDirectory(id="d1", path=real_dir, enabled=True)
            cfg = LocalFileSearchConfig(directories=[d])
            idx = LocalFileIndexer(mock_vector_store, mock_embedding_service, cfg)

            f = Path(real_dir) / "temp.md"
            f.write_text(REALISTIC_TEXT)

            await idx.index_all()
            assert idx.stats.total_files == 1

            f.unlink()
            await idx.index_all()
            assert idx.stats.total_files == 0

    async def test_circuit_breaker(self, mock_vector_store, tmp_path):
        failing_embedding = AsyncMock()
        failing_embedding.embed = AsyncMock(return_value=[0.1] * 1536)
        failing_embedding.embed_batch = AsyncMock(side_effect=RuntimeError("API down"))
        failing_embedding.dimension = 1536

        d = IndexedDirectory(id="d1", path=str(tmp_path), enabled=True)
        cfg = LocalFileSearchConfig(directories=[d])
        idx = LocalFileIndexer(mock_vector_store, failing_embedding, cfg)

        for i in range(6):
            (tmp_path / f"doc{i}.md").write_text(REALISTIC_TEXT + f"\n\nDocument variation {i}.")

        stats = await idx.index_all()
        assert stats.status == IndexStatus.FAILED

    async def test_restore_records(self, indexer):
        records = [
            FileRecord(
                path="/a.txt",
                relative_path="a.txt",
                directory_id="d1",
                content_hash="h1",
                file_size=100,
                file_type="txt",
                chunk_count=3,
            ),
            FileRecord(
                path="/b.txt",
                relative_path="b.txt",
                directory_id="d1",
                content_hash="h2",
                file_size=200,
                file_type="txt",
                chunk_count=5,
            ),
        ]
        indexer.restore_records(records)
        assert indexer.stats.total_files == 2
        assert indexer.stats.total_chunks == 8

    async def test_remove_directory(self, indexer, tmp_path, mock_embedding_service):
        (tmp_path / "doc.md").write_text(REALISTIC_TEXT)
        mock_embedding_service.embed_batch.return_value = [[0.1] * 1536]

        await indexer.index_all()
        assert indexer.stats.total_files == 1

        removed = await indexer.remove_directory("d1")
        assert removed == 1
        assert indexer.stats.total_files == 0

    async def test_file_records_property(self, indexer, tmp_path, mock_embedding_service):
        (tmp_path / "doc.md").write_text(REALISTIC_TEXT)
        mock_embedding_service.embed_batch.return_value = [[0.1] * 1536]

        await indexer.index_all()
        records = indexer.file_records
        assert isinstance(records, dict)
        assert len(records) == 1

    async def test_skip_when_already_indexing(self, indexer, tmp_path, mock_embedding_service):
        """Verify lock prevents concurrent indexing."""
        (tmp_path / "doc.md").write_text(REALISTIC_TEXT)
        mock_embedding_service.embed_batch.return_value = [[0.1] * 1536]

        async with indexer._lock:
            stats = await indexer.index_all()
            assert stats == indexer.stats
