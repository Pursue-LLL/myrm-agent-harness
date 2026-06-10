"""Tests for CodeIndexer — FTS5 + Vector hybrid code indexer.

Covers:
- Database initialization and schema
- Workspace file scanning with exclude/size/binary filters
- Incremental indexing via mtime comparison
- FTS5 keyword search
- CJK bigram tokenization
- Result building and ranking
- File removal from index
- get_stats type correctness
- search_symbol exact name lookup
- Content summary generation
"""

from __future__ import annotations

import asyncio
import os
import textwrap
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_index.config import CodeIndexConfig
from myrm_agent_harness.toolkits.code_index.indexer import (
    CodeIndexer,
    _build_content_summary,
    _tokenize_for_fts,
)
from myrm_agent_harness.toolkits.code_index.symbol_extractor import CodeSymbol


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    """Create a minimal workspace with Python/TS files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.py").write_text(textwrap.dedent("""\
        class AuthService:
            def login(self, username: str, password: str) -> bool:
                return True

            def logout(self, session_id: str) -> None:
                pass

        def verify_token(token: str) -> dict:
            return {}
    """))
    (tmp_path / "src" / "utils.ts").write_text(textwrap.dedent("""\
        export function formatDate(d: Date): string {
            return d.toISOString();
        }

        export interface AppConfig {
            port: number;
            debug: boolean;
        }

        export class Logger {
            log(msg: string): void {}
        }
    """))
    (tmp_path / "README.md").write_text("# Project\n")
    return tmp_path


@pytest.fixture()
def config() -> CodeIndexConfig:
    return CodeIndexConfig(enable_vector_search=False, max_files=1000, batch_size=50)


@pytest.fixture()
def indexer(workspace: Path, config: CodeIndexConfig) -> CodeIndexer:
    return CodeIndexer(workspace, config)


class TestTokenizeForFts:
    """FTS5 query tokenization including CJK bigram."""

    def test_latin_words(self) -> None:
        result = _tokenize_for_fts("auth handler")
        assert '"auth"' in result
        assert '"handler"' in result

    def test_short_words_skipped(self) -> None:
        result = _tokenize_for_fts("a b cd")
        assert '"a"' not in result
        assert '"b"' not in result
        assert '"cd"' in result

    def test_cjk_bigram(self) -> None:
        result = _tokenize_for_fts("认证处理")
        assert '"认证"' in result
        assert '"证处"' in result
        assert '"处理"' in result

    def test_mixed_cjk_latin(self) -> None:
        result = _tokenize_for_fts("用户auth")
        assert '"auth"' in result

    def test_empty_query(self) -> None:
        assert _tokenize_for_fts("") == ""

    def test_single_cjk_char_quoted(self) -> None:
        result = _tokenize_for_fts("认")
        assert '"认"' in result


class TestCodeIndexerInit:
    """Database initialization and schema creation."""

    def test_creates_myrm_dir(self, workspace: Path, config: CodeIndexConfig) -> None:
        myrm_dir = workspace / ".myrm"
        if myrm_dir.exists():
            import shutil
            shutil.rmtree(myrm_dir)
        CodeIndexer(workspace, config)
        assert myrm_dir.exists()

    def test_creates_db_file(self, indexer: CodeIndexer) -> None:
        assert indexer._db_path.exists()

    def test_db_has_tables(self, indexer: CodeIndexer) -> None:
        import sqlite3
        conn = sqlite3.connect(str(indexer._db_path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "code_files" in tables
        assert "code_symbols" in tables
        assert "code_fts" in tables or "code_fts_content" in tables


class TestCodeIndexerScan:
    """Workspace file scanning with filters."""

    def test_finds_py_and_ts_files(self, indexer: CodeIndexer) -> None:
        files = indexer._scan_workspace_files()
        paths = {f[0] for f in files}
        assert any("auth.py" in p for p in paths)
        assert any("utils.ts" in p for p in paths)

    def test_excludes_non_code_files(self, indexer: CodeIndexer) -> None:
        files = indexer._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any(p.endswith(".md") for p in paths)

    def test_excludes_myrm_dir(self, workspace: Path, config: CodeIndexConfig) -> None:
        myrm_dir = workspace / ".myrm"
        myrm_dir.mkdir(exist_ok=True)
        (myrm_dir / "test.py").write_text("x = 1\n")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any(".myrm" in p for p in paths)

    def test_excludes_node_modules(self, workspace: Path, config: CodeIndexConfig) -> None:
        nm = workspace / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {};\n")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any("node_modules" in p for p in paths)

    def test_excludes_large_files(self, workspace: Path) -> None:
        big = workspace / "big.py"
        big.write_text("x = 1\n" * 200_000)
        config = CodeIndexConfig(enable_vector_search=False, max_file_size_bytes=1024)
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any("big.py" in p for p in paths)

    def test_respects_max_files(self, workspace: Path) -> None:
        for i in range(10):
            (workspace / f"file_{i}.py").write_text(f"x_{i} = {i}\n")
        config = CodeIndexConfig(enable_vector_search=False, max_files=3)
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        assert len(files) <= 3


class TestCodeIndexerIndex:
    """Incremental indexing and data correctness."""

    def test_ensure_indexed_returns_stats(self, indexer: CodeIndexer) -> None:
        stats = asyncio.get_event_loop().run_until_complete(indexer.ensure_indexed())
        assert stats["total_files"] >= 2
        assert stats["new_files"] >= 2
        assert stats["updated_files"] == 0
        assert stats["removed_files"] == 0

    def test_second_index_no_changes(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        stats2 = loop.run_until_complete(indexer.ensure_indexed())
        assert stats2["new_files"] == 0
        assert stats2["updated_files"] == 0

    def test_updated_file_reindexed(self, indexer: CodeIndexer, workspace: Path) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())

        auth = workspace / "src" / "auth.py"
        import time
        time.sleep(0.05)
        auth.write_text("def new_func():\n    pass\n")
        os.utime(auth, None)

        stats2 = loop.run_until_complete(indexer.ensure_indexed())
        assert stats2["updated_files"] >= 1

    def test_removed_file_cleaned(self, indexer: CodeIndexer, workspace: Path) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())

        (workspace / "src" / "utils.ts").unlink()
        stats2 = loop.run_until_complete(indexer.ensure_indexed())
        assert stats2["removed_files"] >= 1


class TestCodeIndexerSearch:
    """FTS5 search functionality."""

    def test_search_finds_auth(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        results = loop.run_until_complete(indexer.search("AuthService login"))
        assert len(results) >= 1
        assert any("auth.py" in str(r["file_path"]) for r in results)

    def test_search_returns_score(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        results = loop.run_until_complete(indexer.search("auth"))
        if results:
            assert "score" in results[0]
            assert isinstance(results[0]["score"], float)

    def test_search_returns_language(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        results = loop.run_until_complete(indexer.search("AuthService"))
        if results:
            assert results[0]["language"] == "python"

    def test_search_empty_query(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        results = loop.run_until_complete(indexer.search(""))
        assert results == []

    def test_search_no_match(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        results = loop.run_until_complete(indexer.search("zzzznonexistent"))
        assert results == []

    def test_search_limit(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        results = loop.run_until_complete(indexer.search("auth", limit=1))
        assert len(results) <= 1


class TestCodeIndexerSearchSymbol:
    """Exact symbol name lookup."""

    def test_find_exact_function(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        syms = loop.run_until_complete(indexer.search_symbol("verify_token"))
        assert len(syms) >= 1
        assert syms[0].name == "verify_token"
        assert syms[0].kind == "function"

    def test_find_class(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        syms = loop.run_until_complete(indexer.search_symbol("AuthService"))
        assert len(syms) >= 1
        assert syms[0].kind == "class"

    def test_filter_by_kind(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        syms = loop.run_until_complete(indexer.search_symbol("AuthService", kind="class"))
        assert all(s.kind == "class" for s in syms)

    def test_nonexistent_symbol(self, indexer: CodeIndexer) -> None:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(indexer.ensure_indexed())
        syms = loop.run_until_complete(indexer.search_symbol("ZZZNonExistent"))
        assert syms == []


class TestCodeIndexerStats:
    """get_stats returns correct types and values."""

    def test_stats_after_indexing(self, indexer: CodeIndexer) -> None:
        asyncio.get_event_loop().run_until_complete(indexer.ensure_indexed())
        stats = indexer.get_stats()
        assert isinstance(stats["indexed_files"], int)
        assert isinstance(stats["indexed_symbols"], int)
        assert isinstance(stats["languages"], dict)
        assert stats["indexed_files"] >= 2

    def test_stats_empty_index(self, workspace: Path, config: CodeIndexConfig) -> None:
        empty_ws = workspace / "empty_ws"
        empty_ws.mkdir()
        idx = CodeIndexer(empty_ws, config)
        stats = idx.get_stats()
        assert stats["indexed_files"] == 0
        assert stats["indexed_symbols"] == 0
        assert stats["languages"] == {}

    def test_stats_return_type(self, indexer: CodeIndexer) -> None:
        """Verify the return type matches dict[str, int | dict[str, int]]."""
        asyncio.get_event_loop().run_until_complete(indexer.ensure_indexed())
        stats = indexer.get_stats()
        for key, val in stats.items():
            assert isinstance(val, (int, dict)), f"stats[{key!r}] has unexpected type {type(val)}"
        langs = stats["languages"]
        assert isinstance(langs, dict)
        for lang, cnt in langs.items():
            assert isinstance(lang, str)
            assert isinstance(cnt, int)


class TestCodeIndexerEdgeCases:
    """Edge cases: unicode paths, empty workspace, re-init on existing DB."""

    def test_unicode_filename(self, workspace: Path, config: CodeIndexConfig) -> None:
        (workspace / "模块.py").write_text("def 你好():\n    pass\n")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert any("模块.py" in p for p in paths)

    def test_empty_workspace_no_crash(self, config: CodeIndexConfig, tmp_path: Path) -> None:
        empty = tmp_path / "empty_proj"
        empty.mkdir()
        idx = CodeIndexer(empty, config)
        stats = asyncio.get_event_loop().run_until_complete(idx.ensure_indexed())
        assert stats["total_files"] == 0
        assert stats["new_files"] == 0

    def test_reinit_existing_db(self, indexer: CodeIndexer, config: CodeIndexConfig) -> None:
        """Creating a second CodeIndexer on the same workspace doesn't corrupt DB."""
        asyncio.get_event_loop().run_until_complete(indexer.ensure_indexed())
        idx2 = CodeIndexer(indexer._workspace, config)
        stats = idx2.get_stats()
        assert stats["indexed_files"] >= 2

    def test_search_before_index(self, workspace: Path, config: CodeIndexConfig) -> None:
        """Search on unindexed workspace returns empty results."""
        idx = CodeIndexer(workspace, config)
        results = asyncio.get_event_loop().run_until_complete(idx.search("auth"))
        assert results == []

    def test_binary_files_excluded(self, workspace: Path, config: CodeIndexConfig) -> None:
        (workspace / "image.jpg").write_bytes(b"\xff\xd8\xff\xe0")
        (workspace / "archive.zip").write_bytes(b"PK\x03\x04")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any(p.endswith(".jpg") for p in paths)
        assert not any(p.endswith(".zip") for p in paths)

    def test_hidden_dirs_excluded(self, workspace: Path, config: CodeIndexConfig) -> None:
        hidden = workspace / ".hidden_dir"
        hidden.mkdir()
        (hidden / "secret.py").write_text("x = 1\n")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any(".hidden_dir" in p for p in paths)

    def test_empty_file_excluded(self, workspace: Path, config: CodeIndexConfig) -> None:
        (workspace / "empty.py").write_text("")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert not any("empty.py" in p for p in paths)

    def test_deeply_nested_file(self, workspace: Path, config: CodeIndexConfig) -> None:
        deep = workspace / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.py").write_text("def deeply_nested():\n    pass\n")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert any("deep.py" in p for p in paths)

    def test_symlink_in_workspace(self, workspace: Path, config: CodeIndexConfig) -> None:
        """Symlinks are followed if they resolve to valid files."""
        target = workspace / "src" / "auth.py"
        link = workspace / "link_to_auth.py"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks not supported on this platform")
        idx = CodeIndexer(workspace, config)
        files = idx._scan_workspace_files()
        paths = {f[0] for f in files}
        assert any("link_to_auth.py" in p for p in paths)


class TestBuildContentSummary:
    """Content summary builder for FTS5 indexing."""

    def test_includes_first_lines(self) -> None:
        code = "# Module docstring\nimport os\nimport sys\n"
        summary = _build_content_summary(code, [])
        assert "import os" in summary

    def test_skips_shebang(self) -> None:
        code = "#!/usr/bin/env python\nimport os\n"
        summary = _build_content_summary(code, [])
        assert "#!/usr/bin/env" not in summary

    def test_includes_symbol_names(self) -> None:
        symbols = [
            CodeSymbol(name="foo", kind="function", line=1, signature="def foo():", file_path="t.py"),
            CodeSymbol(name="Bar", kind="class", line=5, signature="class Bar:", file_path="t.py"),
        ]
        summary = _build_content_summary("code\n", symbols)
        assert "foo" in summary
        assert "Bar" in summary

    def test_truncates_at_max_chars(self) -> None:
        long_code = "x = 1\n" * 200
        summary = _build_content_summary(long_code, [], max_chars=100)
        assert len(summary) <= 100
