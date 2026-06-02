import os
import subprocess
from unittest import mock

import pytest

from myrm_agent_harness.utils.workspace_indexer import WorkspaceFileIndexer


@pytest.fixture
def mock_git_repo(tmp_path):
    """Create a mock git repo with some files."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Mock .git directory
    (repo_dir / ".git").mkdir()

    # Add files
    (repo_dir / "file1.txt").touch()
    (repo_dir / "file2.py").touch()

    # Add hidden file
    (repo_dir / ".hidden").touch()

    # Add a directory
    sub_dir = repo_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file3.js").touch()

    return repo_dir


@pytest.fixture
def mock_non_git_repo(tmp_path):
    """Create a mock directory without git."""
    repo_dir = tmp_path / "nongit"
    repo_dir.mkdir()

    # Add files
    (repo_dir / "file1.txt").touch()
    (repo_dir / "file2.py").touch()

    # Add hidden file
    (repo_dir / ".hidden").touch()

    # Add a directory
    sub_dir = repo_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "file3.js").touch()

    # Add an ignored directory
    node_modules = repo_dir / "node_modules"
    node_modules.mkdir()
    (node_modules / "ignore_me.js").touch()

    return repo_dir


@mock.patch("myrm_agent_harness.utils.workspace_indexer.subprocess.run")
def test_list_all_files_git_success(mock_run, mock_git_repo):
    """Test git ls-files successful path."""
    # Mock subprocess.run to return some files
    mock_run.return_value = mock.MagicMock(
        stdout=b"file1.txt\0file2.py\0subdir/file3.js\0",
        returncode=0
    )

    files = WorkspaceFileIndexer.list_all_files(str(mock_git_repo))

    mock_run.assert_called_once()
    assert "git" in mock_run.call_args[0][0]
    assert len(files) == 3

    # Check OS sep conversion
    if os.sep != '/':
        assert f"subdir{os.sep}file3.js" in files
    else:
        assert "subdir/file3.js" in files


@mock.patch("myrm_agent_harness.utils.workspace_indexer.subprocess.run")
def test_list_all_files_git_failure_fallback(mock_run, mock_git_repo):
    """Test git ls-files failure falls back to os.walk."""
    # Make subprocess.run throw an exception
    mock_run.side_effect = subprocess.CalledProcessError(1, "git")

    files = WorkspaceFileIndexer.list_all_files(str(mock_git_repo))

    mock_run.assert_called_once()
    assert len(files) == 3
    # Check that .hidden and .git are ignored
    assert "file1.txt" in files
    assert "file2.py" in files
    assert os.path.join("subdir", "file3.js") in files


def test_list_all_files_non_git_fallback(mock_non_git_repo):
    """Test non-git repo uses fallback."""
    files = WorkspaceFileIndexer.list_all_files(str(mock_non_git_repo))

    assert len(files) == 3
    # Check that .hidden and node_modules are ignored
    assert "file1.txt" in files
    assert "file2.py" in files
    assert os.path.join("subdir", "file3.js") in files
    assert os.path.join("node_modules", "ignore_me.js") not in files


@mock.patch("myrm_agent_harness.utils.workspace_indexer._MAX_FALLBACK_FILES", 1)
def test_fallback_max_files_limit(mock_non_git_repo):
    """Test fallback respects max files limit."""
    files = WorkspaceFileIndexer.list_all_files(str(mock_non_git_repo))
    # It should hit the limit and return early
    assert len(files) == 1
