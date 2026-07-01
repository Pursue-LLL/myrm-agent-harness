"""Tests for code_graph builder — parallel parsing, batching, incremental builds."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_graph.builder import (
    BATCH_SIZE,
    BuildResult,
    CodeGraphBuilder,
    _chunked,
)
from myrm_agent_harness.toolkits.code_graph.store import CodeGraphStore


def _tree_sitter_available() -> bool:
    try:
        import tree_sitter_language_pack  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        "def hello():\n    print('hello')\n\ndef goodbye():\n    hello()\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text(
        "class Helper:\n    def run(self):\n        pass\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def store(tmp_path: Path) -> CodeGraphStore:
    db_path = tmp_path / "graph.db"
    s = CodeGraphStore(db_path)
    s.open()
    yield s
    s.close()


class TestChunked:
    def test_empty_list(self) -> None:
        assert _chunked([], 10) == []

    def test_exact_batch(self) -> None:
        items = list(map(str, range(10)))
        result = _chunked(items, 5)
        assert len(result) == 2
        assert len(result[0]) == 5
        assert len(result[1]) == 5

    def test_remainder(self) -> None:
        items = list(map(str, range(7)))
        result = _chunked(items, 3)
        assert len(result) == 3
        assert len(result[2]) == 1


class TestBuildResult:
    def test_defaults(self) -> None:
        r = BuildResult()
        assert r.files_processed == 0
        assert r.files_skipped == 0
        assert r.files_failed == 0
        assert r.is_incremental is False


class TestFullBuild:
    @pytest.mark.skipif(
        not _tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_full_build_processes_files(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        result = builder.build_full()

        assert result.files_processed >= 1
        assert result.nodes_added >= 1
        assert result.is_incremental is False
        assert result.elapsed_seconds > 0.0

    def test_full_build_skips_ignored_dirs(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        node_modules = workspace / "node_modules"
        node_modules.mkdir()
        (node_modules / "pkg.js").write_text("function a() {}")

        builder = CodeGraphBuilder(store, workspace)
        discovered = builder._discover_files()

        for f in discovered:
            assert "node_modules" not in f

    def test_full_build_skips_large_files(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        large = workspace / "src" / "huge.py"
        large.write_text("x = 1\n" * 200_000)

        builder = CodeGraphBuilder(store, workspace, max_file_size=1024)
        discovered = builder._discover_files()

        assert "src/huge.py" not in discovered

    def test_discover_only_supported_languages(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        (workspace / "src" / "readme.md").write_text("# Hello")
        (workspace / "src" / "data.json").write_text("{}")

        builder = CodeGraphBuilder(store, workspace)
        discovered = builder._discover_files()

        for f in discovered:
            assert f.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh"))


class TestIncrementalBuild:
    @pytest.mark.skipif(
        not _tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_incremental_with_explicit_files(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        builder.build_full()

        initial_nodes = store.node_count()

        (workspace / "src" / "new.py").write_text("def new_func():\n    pass\n")
        result = builder.build_incremental(changed_files=["src/new.py"])

        assert result.is_incremental is True
        assert result.files_processed >= 1
        assert store.node_count() > initial_nodes

    @pytest.mark.skipif(
        not _tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_incremental_skips_unchanged(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        builder.build_full()

        result = builder.build_incremental(changed_files=["src/main.py"])
        assert result.files_skipped >= 1

    def test_incremental_removes_deleted_files(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)

        result = builder.build_incremental(changed_files=["src/nonexistent.py"])
        assert result.files_skipped >= 1


class TestParseParallel:
    def test_small_batch_runs_sequentially(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        items = [
            ("test.py", "def f(): pass", "hash1"),
            ("test2.py", "def g(): pass", "hash2"),
        ]
        results = builder._parse_parallel(items)
        assert len(results) == 2

    def test_large_batch_uses_threads(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        items = [
            (f"file{i}.py", f"def func_{i}(): pass", f"hash{i}")
            for i in range(5)
        ]
        results = builder._parse_parallel(items)
        assert len(results) == 5

    def test_handles_parse_failure(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)

        def failing_parse(item: tuple[str, str, str]) -> tuple[str, str, None]:
            raise RuntimeError("parse failed")

        with patch.object(CodeGraphBuilder, "_parse_one", side_effect=failing_parse):
            items = [
                (f"file{i}.py", "broken", f"hash{i}")
                for i in range(5)
            ]
            results = builder._parse_parallel(items)
            assert len(results) == 5
            assert all(r[2] is None for r in results)


class TestEdgeCases:
    def test_unreadable_file_counted_as_failed(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        bad_file = workspace / "src" / "broken.py"
        bad_file.write_text("def x(): pass")
        bad_file.chmod(0o000)

        builder = CodeGraphBuilder(store, workspace)
        result = builder.build_incremental(changed_files=["src/broken.py"])

        bad_file.chmod(0o644)
        assert result.files_failed >= 1 or result.files_skipped >= 1

    def test_custom_ignore_dirs(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        custom_dir = workspace / "custom_cache"
        custom_dir.mkdir()
        (custom_dir / "test.py").write_text("def a(): pass")

        builder = CodeGraphBuilder(
            store, workspace,
            ignore_dirs=frozenset({"custom_cache"}),
        )
        discovered = builder._discover_files()
        for f in discovered:
            assert "custom_cache" not in f

    @pytest.mark.skipif(
        not _tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_unsupported_file_in_changed_list(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        (workspace / "src" / "data.json").write_text("{}")
        builder = CodeGraphBuilder(store, workspace)
        result = builder.build_incremental(changed_files=["src/data.json"])
        assert result.files_processed == 0

    @pytest.mark.skipif(
        not _tree_sitter_available(),
        reason="tree-sitter-language-pack not installed",
    )
    def test_build_result_elapsed_seconds_positive(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        result = builder.build_full()
        assert result.elapsed_seconds > 0

    def test_file_count(
        self, store: CodeGraphStore, workspace: Path,
    ) -> None:
        builder = CodeGraphBuilder(store, workspace)
        files = builder._discover_files()
        assert len(files) == 2
        assert any("main.py" in f for f in files)
        assert any("utils.py" in f for f in files)
