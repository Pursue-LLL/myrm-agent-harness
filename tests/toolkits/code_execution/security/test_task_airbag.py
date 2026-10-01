"""Unit tests for unattended task safety airbag and time-travel rollback suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from myrm_agent_harness.api.security import (
    TaskAirbagStatus,
    arm_task_airbag,
    get_task_airbag_diff,
    rollback_task_airbag,
)


@pytest.fixture
def git_workspace(tmp_path: Path) -> Path:
    """Create a temporary initialized Git repository with initial commit."""
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "tester@myrm.ai"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )

    test_file = tmp_path / "hello.txt"
    test_file.write_text("initial content\n", encoding="utf-8")

    subprocess.run(["git", "add", "hello.txt"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    return tmp_path


@pytest.fixture
def non_git_workspace(tmp_path: Path) -> Path:
    """Create a non-Git workspace directory with files."""
    w = tmp_path / "plain_dir"
    w.mkdir()
    (w / "app.py").write_text("print('hello')", encoding="utf-8")
    return w


@pytest.mark.asyncio
async def test_arm_task_airbag_git_repo(git_workspace: Path) -> None:
    manifest = await arm_task_airbag("task-001", git_workspace)
    assert manifest is not None
    assert manifest.task_id == "task-001"
    assert manifest.is_git_repo is True
    assert manifest.status == TaskAirbagStatus.ARMED
    assert manifest.base_snapshot_id is not None


@pytest.mark.asyncio
async def test_rollback_task_airbag_git_repo(git_workspace: Path) -> None:
    manifest = await arm_task_airbag("task-002", git_workspace)
    assert manifest is not None

    # Agent mutates existing file and creates new file
    target = git_workspace / "hello.txt"
    target.write_text("corrupted content by agent\n", encoding="utf-8")
    new_file = git_workspace / "rogue.py"
    new_file.write_text("import os; os.system('echo bad')\n", encoding="utf-8")

    # Verify diff before rollback
    diff = await get_task_airbag_diff(manifest)
    assert diff.total_files_changed >= 1
    assert "hello.txt" in diff.modified_files

    # Perform time-travel rollback
    success = await rollback_task_airbag(manifest)
    assert success is True

    # Verify workspace completely restored
    assert target.read_text(encoding="utf-8") == "initial content\n"


@pytest.mark.asyncio
async def test_task_airbag_diff_with_external_effects(git_workspace: Path) -> None:
    manifest = await arm_task_airbag("task-003", git_workspace)
    assert manifest is not None

    manifest_with_fx = manifest.with_external_effects(["docker run redis", "curl -X POST"])
    diff = await get_task_airbag_diff(manifest_with_fx)
    assert "docker run redis" in diff.external_effects
    assert "curl -X POST" in diff.external_effects


@pytest.mark.asyncio
async def test_arm_and_rollback_non_git_repo(non_git_workspace: Path) -> None:
    manifest = await arm_task_airbag("task-non-git", non_git_workspace)
    assert manifest is not None
    assert manifest.is_git_repo is False
    assert manifest.status == TaskAirbagStatus.ARMED

    # Mutate
    f = non_git_workspace / "app.py"
    f.write_text("print('mutated')", encoding="utf-8")

    # Rollback
    success = await rollback_task_airbag(manifest)
    assert success is True
    assert f.read_text(encoding="utf-8") == "print('hello')"


@pytest.mark.asyncio
async def test_task_airbag_invalid_path() -> None:
    manifest = await arm_task_airbag("task-invalid", Path("/non/existent/path/xyz"))
    assert manifest is None
