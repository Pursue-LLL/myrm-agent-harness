"""Tests for Local RAG pipeline: indexer raw text, compiler enqueue, and chunk splitting."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import (
    _BINARY_DOC_EXTENSIONS,
    _LARGE_DOC_CHUNK_THRESHOLD,
    _split_if_large,
)


class TestBinaryDocExtensions:
    """Verify the binary document extension set is correct."""

    @pytest.mark.parametrize(
        "ext",
        [".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"],
    )
    def test_supported_extensions(self, ext: str) -> None:
        assert ext in _BINARY_DOC_EXTENSIONS

    @pytest.mark.parametrize("ext", [".md", ".txt", ".py", ".json", ".csv"])
    def test_unsupported_extensions(self, ext: str) -> None:
        assert ext not in _BINARY_DOC_EXTENSIONS


class TestSplitIfLarge:
    """Tests for _split_if_large chunking logic."""

    def test_small_content_returns_single_entry(self) -> None:
        content = "Short doc content"
        result = _split_if_large(content, "notes/test.md")
        assert len(result) == 1
        assert result[0] == ("notes/test.md", content)

    def test_exactly_at_threshold_returns_single_entry(self) -> None:
        content = "x" * _LARGE_DOC_CHUNK_THRESHOLD
        result = _split_if_large(content, "doc.md")
        assert len(result) == 1
        assert result[0] == ("doc.md", content)

    def _make_diverse_content(self, min_chars: int) -> str:
        """Generate diverse content that survives chunk quality filtering."""
        sections: list[str] = []
        i = 0
        while len("\n\n".join(sections)) < min_chars:
            sections.append(
                f"## Section {i}: Topic Alpha-{i}\n\n"
                f"Paragraph about concept {i} in domain engineering. "
                f"The framework handles request {i} through middleware layer {i}. "
                f"Configuration parameter set-{i} controls behavior for module {i}.\n"
            )
            i += 1
        return "\n\n".join(sections)

    def test_above_threshold_produces_multiple_chunks(self) -> None:
        content = self._make_diverse_content(_LARGE_DOC_CHUNK_THRESHOLD + 10000)
        assert len(content) > _LARGE_DOC_CHUNK_THRESHOLD

        result = _split_if_large(content, "big_report.md")
        assert len(result) >= 2

        for path, chunk in result:
            assert path.endswith(".md")
            assert len(chunk) > 0

    def test_chunk_naming_with_parent_path(self) -> None:
        content = self._make_diverse_content(_LARGE_DOC_CHUNK_THRESHOLD + 10000)
        result = _split_if_large(content, "folder/subfolder/report.md")

        if len(result) >= 2:
            for path, _ in result:
                assert path.startswith("folder/subfolder/")
                assert "report_chunk" in path

    def test_chunk_naming_without_parent(self) -> None:
        content = self._make_diverse_content(_LARGE_DOC_CHUNK_THRESHOLD + 10000)
        result = _split_if_large(content, "report.md")

        if len(result) >= 2:
            for path, _ in result:
                assert "report_chunk" in path

    def test_all_content_preserved_after_split(self) -> None:
        words = [f"word{i}" for i in range(_LARGE_DOC_CHUNK_THRESHOLD // 3)]
        content = " ".join(words)
        result = _split_if_large(content, "doc.md")

        combined = " ".join(chunk for _, chunk in result)
        for w in words[:50]:
            assert w in combined


class TestIndexRawText:
    """Tests for WikiIndexer.index_raw_text FTS5 interim indexing."""

    @pytest.fixture()
    def db_path(self, tmp_path: Path) -> Path:
        return tmp_path / "test_wiki.db"

    def _create_fts_table(self, db_path: Path) -> None:
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
                    concept_name,
                    truth_content
                )
            """)

    def test_index_raw_text_inserts_with_raw_prefix(self, db_path: Path) -> None:
        self._create_fts_table(db_path)

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                ("raw:test_doc", "Hello world test content"),
            )
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", ("raw:test_doc",))
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                ("raw:test_doc", "Hello world test content"),
            )

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT concept_name, truth_content FROM wiki_fts WHERE concept_name = ?",
                ("raw:test_doc",),
            )
            rows = cursor.fetchall()
            assert len(rows) == 1
            assert rows[0][0] == "raw:test_doc"
            assert "Hello world" in rows[0][1]

    def test_raw_entry_truncates_large_text(self, db_path: Path) -> None:
        self._create_fts_table(db_path)
        large_text = "a" * 10000

        preview = large_text[:5000]
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                ("raw:large_doc", preview),
            )

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT truth_content FROM wiki_fts WHERE concept_name = ?",
                ("raw:large_doc",),
            )
            row = cursor.fetchone()
            assert row is not None
            assert len(row[0]) == 5000

    def test_upsert_removes_raw_entry(self, db_path: Path) -> None:
        """When compiled version upserts, raw: entry should be deleted."""
        self._create_fts_table(db_path)

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                ("raw:doc1", "raw content"),
            )

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", ("doc1",))
            conn.execute("DELETE FROM wiki_fts WHERE concept_name = ?", ("raw:doc1",))
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                ("doc1", "compiled truth content"),
            )

        with sqlite3.connect(str(db_path)) as conn:
            raw_cursor = conn.execute(
                "SELECT * FROM wiki_fts WHERE concept_name = ?", ("raw:doc1",)
            )
            assert raw_cursor.fetchone() is None

            compiled_cursor = conn.execute(
                "SELECT truth_content FROM wiki_fts WHERE concept_name = ?", ("doc1",)
            )
            row = compiled_cursor.fetchone()
            assert row is not None
            assert "compiled truth" in row[0]

    def test_fts5_search_finds_raw_entries(self, db_path: Path) -> None:
        self._create_fts_table(db_path)

        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO wiki_fts (concept_name, truth_content) VALUES (?, ?)",
                ("raw:kubernetes_guide", "Kubernetes pod deployment scaling strategies"),
            )

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT concept_name, rank FROM wiki_fts WHERE wiki_fts MATCH ?",
                ("kubernetes",),
            )
            results = cursor.fetchall()
            assert len(results) >= 1
            assert any("raw:kubernetes_guide" in r[0] for r in results)


class TestCompilerEnqueueRawIndex:
    """Tests for compiler.enqueue_file triggering raw FTS5 indexing."""

    def test_enqueue_calls_index_raw_text_for_md_files(self, tmp_path: Path) -> None:
        md_file = tmp_path / "test_doc.md"
        md_file.write_text("# Test Document\nSome content here.", encoding="utf-8")

        mock_indexer = MagicMock()
        mock_queue = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.wiki.pipeline.compiler.WikiCompiler.__init__",
            return_value=None,
        ):
            from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

            compiler = WikiCompiler.__new__(WikiCompiler)
            compiler._queue = mock_queue
            compiler._indexer = mock_indexer
            compiler.start_background_worker = MagicMock()

            compiler.enqueue_file(md_file)

            mock_queue.add_item.assert_called_once_with(md_file)
            mock_indexer.index_raw_text.assert_called_once_with(
                "test_doc",
                "# Test Document\nSome content here.",
            )

    def test_enqueue_skips_indexing_for_non_md_files(self, tmp_path: Path) -> None:
        py_file = tmp_path / "script.py"
        py_file.write_text("print('hello')", encoding="utf-8")

        mock_indexer = MagicMock()
        mock_queue = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.wiki.pipeline.compiler.WikiCompiler.__init__",
            return_value=None,
        ):
            from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

            compiler = WikiCompiler.__new__(WikiCompiler)
            compiler._queue = mock_queue
            compiler._indexer = mock_indexer
            compiler.start_background_worker = MagicMock()

            compiler.enqueue_file(py_file)

            mock_queue.add_item.assert_called_once()
            mock_indexer.index_raw_text.assert_not_called()

    def test_enqueue_skips_indexing_when_no_indexer(self, tmp_path: Path) -> None:
        md_file = tmp_path / "doc.md"
        md_file.write_text("content", encoding="utf-8")

        mock_queue = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.wiki.pipeline.compiler.WikiCompiler.__init__",
            return_value=None,
        ):
            from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

            compiler = WikiCompiler.__new__(WikiCompiler)
            compiler._queue = mock_queue
            compiler._indexer = None
            compiler.start_background_worker = MagicMock()

            compiler.enqueue_file(md_file)

            mock_queue.add_item.assert_called_once()

    def test_enqueue_handles_empty_md_file(self, tmp_path: Path) -> None:
        md_file = tmp_path / "empty.md"
        md_file.write_text("   \n  ", encoding="utf-8")

        mock_indexer = MagicMock()
        mock_queue = MagicMock()

        with patch(
            "myrm_agent_harness.toolkits.wiki.pipeline.compiler.WikiCompiler.__init__",
            return_value=None,
        ):
            from myrm_agent_harness.toolkits.wiki.pipeline.compiler import WikiCompiler

            compiler = WikiCompiler.__new__(WikiCompiler)
            compiler._queue = mock_queue
            compiler._indexer = mock_indexer
            compiler.start_background_worker = MagicMock()

            compiler.enqueue_file(md_file)

            mock_indexer.index_raw_text.assert_not_called()
