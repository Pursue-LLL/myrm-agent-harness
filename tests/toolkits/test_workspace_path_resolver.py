"""Tests for intelligent workspace path resolver."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import (
    WorkspacePathResolver,
)


class TestWorkspacePathResolver:
    """Test intelligent workspace root resolution."""

    def setup_method(self):
        """Clear cached workspace root before each test."""
        WorkspacePathResolver._cached_workspace_root = None

    def test_resolve_from_env_var(self, tmp_path):
        """Test: WORKSPACE_ROOT env var takes highest priority."""
        with patch.dict(os.environ, {"WORKSPACE_ROOT": str(tmp_path)}):
            result = WorkspacePathResolver.resolve_workspace_root()
            assert result == tmp_path

    def test_resolve_from_container_workspace(self, tmp_path):
        """Test: Container /workspace detection."""
        with patch.object(Path, "exists", return_value=True):
            with patch.object(WorkspacePathResolver, "_is_in_container", return_value=True):
                result = WorkspacePathResolver.resolve_workspace_root()
                assert result == Path("/workspace")

    def test_resolve_from_project_markers(self, tmp_path):
        """Test: Detect project root from .git marker."""
        # Create .git marker
        (tmp_path / ".git").mkdir()

        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result = WorkspacePathResolver.resolve_workspace_root()
            assert result == tmp_path

    def test_resolve_fallback_to_cwd(self, tmp_path):
        """Test: Fallback to current working directory."""
        with patch("pathlib.Path.cwd", return_value=tmp_path), patch.dict(os.environ, {}, clear=True):
            result = WorkspacePathResolver.resolve_workspace_root()
            assert result == tmp_path

    def test_to_local_path_auto_resolve(self, tmp_path):
        """Test: to_local_path auto-resolves workspace_root if None."""
        with patch.object(WorkspacePathResolver, "resolve_workspace_root", return_value=tmp_path):
            result = WorkspacePathResolver.to_local_path("/workspace/test.py", workspace_root=None)
            assert result == tmp_path / "test.py"

    def test_detect_project_root_with_pyproject(self, tmp_path):
        """Test: Detect project root from pyproject.toml."""
        (tmp_path / "pyproject.toml").touch()
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        with patch("pathlib.Path.cwd", return_value=subdir):
            result = WorkspacePathResolver._detect_project_root()
            assert result == tmp_path

    def test_is_in_container_dockerenv(self):
        """Test: Container detection via /.dockerenv."""
        with patch.object(Path, "exists", side_effect=lambda: True):
            assert WorkspacePathResolver._is_in_container()

    def test_is_in_container_k8s(self):
        """Test: Container detection via K8S env var."""
        with patch.dict(os.environ, {"KUBERNETES_SERVICE_HOST": "127.0.0.1"}):
            assert WorkspacePathResolver._is_in_container()

    def test_generate_diagnostics(self, tmp_path):
        """Test: Diagnostic information generation."""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            diagnostics = WorkspacePathResolver._generate_diagnostics()

            assert "cwd" in diagnostics
            assert "is_container" in diagnostics
            assert "detected_markers" in diagnostics
            assert diagnostics["cwd"] == str(tmp_path)

    def test_caching_workspace_root(self, tmp_path):
        """Test: Workspace root is cached after first resolution."""
        with patch("pathlib.Path.cwd", return_value=tmp_path):
            result1 = WorkspacePathResolver.resolve_workspace_root()
            result2 = WorkspacePathResolver.resolve_workspace_root()

            assert result1 == result2
            assert WorkspacePathResolver._cached_workspace_root == tmp_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
