from __future__ import annotations

import os
import subprocess
from unittest import mock

import pytest

from myrm_agent_harness.toolkits.filesystem_suggest.indexer import WorkspacePathIndexer


@pytest.fixture
def mock_non_git_repo(tmp_path):
    repo_dir = tmp_path / "nongit"
    repo_dir.mkdir()
    (repo_dir / "file1.txt").touch()
    (repo_dir / "file2.py").touch()
    (repo_dir / ".hidden").touch()
    sub_dir = repo_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file3.js").touch()
    node_modules = repo_dir / "node_modules"
    node_modules.mkdir()
    (node_modules / "ignore_me.js").touch()
    return repo_dir


def test_list_files_non_git_fallback(mock_non_git_repo):
    WorkspacePathIndexer.clear_cache(mock_non_git_repo)
    files = WorkspacePathIndexer.list_files(mock_non_git_repo)

    assert len(files) == 3
    assert "file1.txt" in files
    assert "file2.py" in files
    assert "subdir/file3.js" in files
    assert "node_modules/ignore_me.js" not in files


@mock.patch("myrm_agent_harness.toolkits.filesystem_suggest.indexer.subprocess.run")
def test_list_files_git_success(mock_run, tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()
    (repo_dir / "file1.txt").touch()

    mock_run.side_effect = [
        mock.MagicMock(returncode=0, stdout=str(repo_dir).encode()),
        mock.MagicMock(returncode=0, stdout=b"file1.txt\0"),
    ]

    WorkspacePathIndexer.clear_cache(repo_dir)
    files = WorkspacePathIndexer.list_files(repo_dir)

    assert files == ["file1.txt"]
    assert mock_run.call_count == 2


@mock.patch("myrm_agent_harness.toolkits.filesystem_suggest.indexer.subprocess.run")
def test_list_files_git_failure_fallback(mock_run, mock_non_git_repo):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=2.0)

    WorkspacePathIndexer.clear_cache(mock_non_git_repo)
    files = WorkspacePathIndexer.list_files(mock_non_git_repo)

    assert len(files) == 3
    if os.sep != "/":
        assert os.path.join("subdir", "file3.js") in files
    else:
        assert "subdir/file3.js" in files
