"""Unit tests for file_scanner module.

Tests the LocalFilesScanner directory filtering and file discovery behavior.
"""

import asyncio
import os
import time

import pytest

from myrm_agent_harness.toolkits.code_execution.executors.common.file_scanner import (
    LocalFilesScanner,
    _SCAN_SKIP_DIRS,
)


@pytest.fixture
def workspace(tmp_path):
    """Create a workspace with normal files and ignored directories."""
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "output.txt").write_text("result")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("app code")

    for skip_dir in ["node_modules", "__pycache__", ".venv", "dist", "build"]:
        d = tmp_path / skip_dir
        d.mkdir()
        (d / "junk.txt").write_text("should be skipped")
        if skip_dir == "node_modules":
            nested = d / "some_package"
            nested.mkdir()
            (nested / "index.js").write_text("module.exports = {}")

    (tmp_path / ".hidden_dir").mkdir()
    (tmp_path / ".hidden_dir" / "secret.txt").write_text("hidden")

    (tmp_path / ".DS_Store").write_text("mac junk")
    (tmp_path / ".gitignore").write_text("*.pyc")

    return tmp_path


class TestScanSkipDirs:
    """Tests for _SCAN_SKIP_DIRS constant."""

    def test_is_frozenset(self):
        assert isinstance(_SCAN_SKIP_DIRS, frozenset)

    def test_contains_critical_dirs(self):
        critical = {"node_modules", "__pycache__", ".git", ".venv", "dist", "build"}
        assert critical.issubset(_SCAN_SKIP_DIRS)

    def test_lookup_is_o1(self):
        assert "node_modules" in _SCAN_SKIP_DIRS
        assert "random_dir" not in _SCAN_SKIP_DIRS


class TestLocalFilesScanner:
    """Tests for LocalFilesScanner.scan()."""

    @pytest.mark.asyncio
    async def test_skips_ignored_directories(self, workspace):
        scanner = LocalFilesScanner()
        start_time = time.time() - 1.0
        results = await scanner.scan(start_time, workspace)

        result_paths = {os.path.basename(p) for p in results}

        assert "main.py" in result_paths
        assert "output.txt" in result_paths
        assert "app.py" in result_paths
        assert "junk.txt" not in result_paths
        assert "index.js" not in result_paths

    @pytest.mark.asyncio
    async def test_skips_dotfiles(self, workspace):
        scanner = LocalFilesScanner()
        start_time = time.time() - 1.0
        results = await scanner.scan(start_time, workspace)

        result_paths = {os.path.basename(p) for p in results}

        assert ".DS_Store" not in result_paths
        assert ".gitignore" not in result_paths

    @pytest.mark.asyncio
    async def test_skips_hidden_directories(self, workspace):
        scanner = LocalFilesScanner()
        start_time = time.time() - 1.0
        results = await scanner.scan(start_time, workspace)

        result_paths = {os.path.basename(p) for p in results}

        assert "secret.txt" not in result_paths

    @pytest.mark.asyncio
    async def test_respects_mtime_threshold(self, workspace):
        scanner = LocalFilesScanner()
        future_time = time.time() + 3600
        results = await scanner.scan(future_time, workspace)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_returns_absolute_paths(self, workspace):
        scanner = LocalFilesScanner()
        start_time = time.time() - 1.0
        results = await scanner.scan(start_time, workspace)

        for path in results:
            assert os.path.isabs(path)

    @pytest.mark.asyncio
    async def test_none_workspace(self):
        scanner = LocalFilesScanner()
        results = await scanner.scan(time.time(), None)
        assert results == []

    @pytest.mark.asyncio
    async def test_nonexistent_workspace(self, tmp_path):
        scanner = LocalFilesScanner()
        nonexistent = tmp_path / "does_not_exist"
        results = await scanner.scan(time.time(), nonexistent)
        assert results == []

    @pytest.mark.asyncio
    async def test_all_scan_skip_dirs_are_filtered(self, tmp_path):
        """Verify every directory in _SCAN_SKIP_DIRS is actually skipped."""
        for skip_dir in list(_SCAN_SKIP_DIRS)[:10]:
            d = tmp_path / skip_dir
            d.mkdir(exist_ok=True)
            (d / "marker.txt").write_text("should not appear")

        (tmp_path / "visible.py").write_text("visible")

        scanner = LocalFilesScanner()
        start_time = time.time() - 1.0
        results = await scanner.scan(start_time, tmp_path)

        result_paths = {os.path.basename(p) for p in results}
        assert "visible.py" in result_paths
        assert "marker.txt" not in result_paths
