"""Unit tests for local_file_search.models."""

from datetime import datetime

from myrm_agent_harness.toolkits.local_file_search.models import (
    FileRecord,
    IndexedDirectory,
    IndexStats,
    IndexStatus,
    SearchHit,
    SearchResponse,
)


class TestIndexStatus:
    def test_enum_values(self):
        assert IndexStatus.IDLE == "idle"
        assert IndexStatus.INDEXING == "indexing"
        assert IndexStatus.FAILED == "failed"


class TestIndexedDirectory:
    def test_defaults(self):
        d = IndexedDirectory(path="/tmp/docs")
        assert d.path == "/tmp/docs"
        assert d.recursive is True
        assert d.enabled is True
        assert d.id  # auto-generated uuid
        assert isinstance(d.created_at, datetime)

    def test_custom_values(self):
        d = IndexedDirectory(
            id="dir-1", path="/data", recursive=False, enabled=False
        )
        assert d.id == "dir-1"
        assert d.recursive is False
        assert d.enabled is False

    def test_json_roundtrip(self):
        d = IndexedDirectory(path="/tmp/test")
        data = d.model_dump(mode="json")
        restored = IndexedDirectory.model_validate(data)
        assert restored.path == d.path
        assert restored.id == d.id


class TestFileRecord:
    def test_defaults(self):
        r = FileRecord(
            path="/tmp/test.pdf",
            relative_path="test.pdf",
            directory_id="dir-1",
            content_hash="abc123",
            file_size=1024,
            file_type="pdf",
        )
        assert r.chunk_count == 0
        assert r.error is None
        assert r.id  # auto-generated

    def test_json_roundtrip(self):
        r = FileRecord(
            path="/tmp/test.md",
            relative_path="test.md",
            directory_id="d1",
            content_hash="sha256hash",
            file_size=512,
            file_type="md",
            chunk_count=5,
        )
        data = r.model_dump(mode="json")
        restored = FileRecord.model_validate(data)
        assert restored.path == r.path
        assert restored.content_hash == r.content_hash
        assert restored.chunk_count == 5


class TestIndexStats:
    def test_defaults(self):
        s = IndexStats()
        assert s.total_files == 0
        assert s.total_chunks == 0
        assert s.status == IndexStatus.IDLE
        assert s.last_indexed_at is None
        assert s.indexing_progress == 0.0
        assert s.current_file is None
        assert s.error_count == 0

    def test_progress_bounds(self):
        s = IndexStats(indexing_progress=0.5)
        assert s.indexing_progress == 0.5


class TestSearchHit:
    def test_creation(self):
        h = SearchHit(
            file_path="/docs/report.pdf",
            relative_path="report.pdf",
            snippet="Important findings...",
            score=0.95,
            file_type="pdf",
        )
        assert h.section == ""
        assert h.score == 0.95

    def test_with_section(self):
        h = SearchHit(
            file_path="/a.md",
            relative_path="a.md",
            snippet="text",
            score=0.8,
            file_type="md",
            section="## Introduction",
        )
        assert h.section == "## Introduction"


class TestSearchResponse:
    def test_empty_defaults(self):
        r = SearchResponse()
        assert r.hits == []
        assert r.total_hits == 0
        assert r.query == ""
        assert r.search_time_ms == 0.0

    def test_with_hits(self):
        hit = SearchHit(
            file_path="/a.txt",
            relative_path="a.txt",
            snippet="content",
            score=0.9,
            file_type="txt",
        )
        r = SearchResponse(hits=[hit], total_hits=1, query="test", search_time_ms=15.0)
        assert len(r.hits) == 1
        assert r.total_hits == 1
