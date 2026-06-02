"""Tests for venv path security whitelist in LocalExecutor.

Covers:
1. _get_venv_additional_paths — returns venv path when exists, None otherwise
2. validate_command + venv whitelist — venv paths allowed, non-whitelist blocked
3. Security non-degradation — forbidden paths remain blocked even with whitelist
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import (
    LocalExecutor,
)
from myrm_agent_harness.toolkits.code_execution.security.validator import (
    _get_allowed_paths,
    _is_path_allowed,
    validate_command,
)


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def tmp_venv(tmp_path: Path) -> Path:
    venv = tmp_path / ".sandbox_venv"
    venv.mkdir()
    (venv / "bin").mkdir()
    (venv / "bin" / "python").touch()
    (venv / "bin" / "pip").touch()
    return venv


@pytest.fixture
def executor_with_venv(tmp_venv: Path, tmp_workspace: Path) -> LocalExecutor:
    config = ExecutionConfig(local={"shared_venv_path": str(tmp_venv)})
    executor = LocalExecutor(config, workspace_path=str(tmp_workspace))
    return executor


@pytest.fixture
def executor_without_venv(tmp_path: Path, tmp_workspace: Path) -> LocalExecutor:
    nonexistent = tmp_path / "no_such_venv"
    config = ExecutionConfig(local={"shared_venv_path": str(nonexistent)})
    executor = LocalExecutor(config, workspace_path=str(tmp_workspace))
    return executor


class TestGetVenvAdditionalPaths:
    """Unit tests for LocalExecutor._get_venv_additional_paths."""

    def test_returns_venv_path_when_exists(
        self, executor_with_venv: LocalExecutor, tmp_venv: Path
    ) -> None:
        result = executor_with_venv._get_venv_additional_paths()
        assert result is not None
        assert len(result) == 1
        assert result[0] == tmp_venv

    def test_returns_none_when_venv_missing(
        self, executor_without_venv: LocalExecutor
    ) -> None:
        result = executor_without_venv._get_venv_additional_paths()
        assert result is None

    def test_return_type_matches_additional_paths_signature(
        self, executor_with_venv: LocalExecutor
    ) -> None:
        result = executor_with_venv._get_venv_additional_paths()
        assert isinstance(result, list)
        assert all(isinstance(p, Path) for p in result)


class TestValidateCommandWithVenvWhitelist:
    """Integration tests: validate_command + venv as additional_paths."""

    def test_venv_python_path_allowed(
        self, tmp_workspace: Path, tmp_venv: Path
    ) -> None:
        python_path = str(tmp_venv / "bin" / "python")
        script = tmp_workspace / "run.py"
        script.touch()
        cmd = f"{python_path} {script}"
        result = validate_command(
            cmd,
            workspace_path=tmp_workspace,
            additional_paths=[tmp_venv],
        )
        assert result.is_safe, f"Expected safe, got: {result.reason}"

    def test_venv_pip_path_allowed(self, tmp_workspace: Path, tmp_venv: Path) -> None:
        pip_path = str(tmp_venv / "bin" / "pip")
        cmd = f"{pip_path} install reportlab"
        result = validate_command(
            cmd,
            workspace_path=tmp_workspace,
            additional_paths=[tmp_venv],
        )
        assert result.is_safe, f"Expected safe, got: {result.reason}"

    def test_non_whitelist_path_still_blocked(
        self, tmp_workspace: Path, tmp_venv: Path
    ) -> None:
        cmd = "/usr/local/bin/evil_script.sh"
        result = validate_command(
            cmd,
            workspace_path=tmp_workspace,
            additional_paths=[tmp_venv],
        )
        assert not result.is_safe
        assert "Access denied" in (result.reason or "")

    def test_workspace_path_still_allowed(
        self, tmp_workspace: Path, tmp_venv: Path
    ) -> None:
        script = tmp_workspace / "my_script.py"
        script.touch()
        cmd = f"python {script}"
        result = validate_command(
            cmd,
            workspace_path=tmp_workspace,
            additional_paths=[tmp_venv],
        )
        assert result.is_safe

    def test_without_additional_paths_venv_blocked(
        self, tmp_workspace: Path, tmp_venv: Path
    ) -> None:
        """Before the fix: venv paths are blocked without additional_paths."""
        python_path = str(tmp_venv / "bin" / "python")
        script = tmp_workspace / "run.py"
        script.touch()
        cmd = f"{python_path} {script}"
        result = validate_command(
            cmd,
            workspace_path=tmp_workspace,
            additional_paths=None,
        )
        assert not result.is_safe
        assert "Access denied" in (result.reason or "")


class TestValidateCommandCoreSecurityPaths:
    """Ensure core path security remains intact."""

    def test_relative_path_without_traversal_allowed(self, tmp_workspace: Path) -> None:
        result = validate_command(
            "cat output.txt",
            workspace_path=tmp_workspace,
        )
        assert result.is_safe

    def test_absolute_workspace_path_allowed(self, tmp_workspace: Path) -> None:
        target = tmp_workspace / "data.csv"
        target.touch()
        result = validate_command(
            f"cat {target}",
            workspace_path=tmp_workspace,
        )
        assert result.is_safe

    def test_absolute_outside_workspace_blocked(self, tmp_workspace: Path) -> None:
        result = validate_command(
            "cat /etc/passwd",
            workspace_path=tmp_workspace,
        )
        assert not result.is_safe

    def test_tmp_path_allowed(self, tmp_workspace: Path) -> None:
        result = validate_command(
            "ls /tmp/some_file",
            workspace_path=tmp_workspace,
        )
        assert result.is_safe


class TestGetAllowedPaths:
    """Unit tests for _get_allowed_paths helper."""

    def test_workspace_only(self, tmp_workspace: Path) -> None:
        paths = _get_allowed_paths(workspace_path=tmp_workspace)
        assert tmp_workspace.resolve() in paths
        assert Path("/workspace") in paths
        assert Path("/tmp") in paths

    def test_with_additional_paths(self, tmp_workspace: Path, tmp_venv: Path) -> None:
        paths = _get_allowed_paths(
            workspace_path=tmp_workspace,
            additional_paths=[tmp_venv],
        )
        assert tmp_venv.resolve() in paths
        assert tmp_workspace.resolve() in paths

    def test_no_paths(self) -> None:
        paths = _get_allowed_paths()
        assert Path("/workspace") in paths
        assert Path("/tmp") in paths
        assert Path("/persistent/.context") in paths
        assert len(paths) == 3


class TestIsPathAllowed:
    """Unit tests for _is_path_allowed."""

    def test_relative_path_safe(self, tmp_workspace: Path) -> None:
        allowed = _get_allowed_paths(workspace_path=tmp_workspace)
        assert _is_path_allowed("output.txt", allowed) is True

    def test_absolute_allowed(self, tmp_workspace: Path) -> None:
        allowed = _get_allowed_paths(workspace_path=tmp_workspace)
        target = str(tmp_workspace / "file.py")
        assert _is_path_allowed(target, allowed) is True

    def test_absolute_blocked(self, tmp_workspace: Path) -> None:
        allowed = _get_allowed_paths(workspace_path=tmp_workspace)
        assert _is_path_allowed("/etc/shadow", allowed) is False

    def test_venv_path_with_additional(
        self, tmp_workspace: Path, tmp_venv: Path
    ) -> None:
        allowed = _get_allowed_paths(
            workspace_path=tmp_workspace,
            additional_paths=[tmp_venv],
        )
        python_path = str(tmp_venv / "bin" / "python")
        assert _is_path_allowed(python_path, allowed) is True

    def test_venv_path_without_additional_blocked(
        self, tmp_workspace: Path, tmp_venv: Path
    ) -> None:
        allowed = _get_allowed_paths(workspace_path=tmp_workspace)
        python_path = str(tmp_venv / "bin" / "python")
        assert _is_path_allowed(python_path, allowed) is False
