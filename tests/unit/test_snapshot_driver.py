"""Unit tests for SnapshotDriverProtocol and high impact action evaluation.

[POS]
Tests copy-on-write snapshot driver, fallback shadow git driver, and
high-impact command evaluation parser.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from myrm_agent_harness.agent.file_snapshot.snapshot_driver import (
    ReflinkSnapshotDriver,
    ShadowGitSnapshotDriver,
    get_default_snapshot_driver,
    SnapshotDriverProtocol,
)
from myrm_agent_harness.agent.meta_tools.bash._security.preflight_checks import (
    evaluate_high_impact_command,
    check_destructive_commands,
)
from myrm_agent_harness.utils.errors import ToolError


@pytest.mark.asyncio
async def test_reflink_snapshot_driver_create_and_restore() -> None:
    """Test creating a snapshot and restoring it using ReflinkSnapshotDriver."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_path = Path(tmp_dir)
        workspace = root_path / "workspace"
        workspace.mkdir()
        storage = root_path / "snapshots"

        # 1. Create initial files
        file1 = workspace / "test.txt"
        file1.write_text("initial content", encoding="utf-8")

        driver = ReflinkSnapshotDriver(storage_root=storage)
        assert isinstance(driver, SnapshotDriverProtocol)

        # 2. Take snapshot
        snap_ref = await driver.create_snapshot("chk_001", workspace)
        assert snap_ref.snapshot_id == "chk_001"
        assert snap_ref.file_count >= 1

        # 3. Modify workspace
        file1.write_text("corrupted content", encoding="utf-8")
        file2 = workspace / "new_file.txt"
        file2.write_text("unwanted addition", encoding="utf-8")

        # 4. Restore snapshot
        success = await driver.restore_snapshot(snap_ref, workspace)
        assert success is True
        assert file1.read_text(encoding="utf-8") == "initial content"


@pytest.mark.asyncio
async def test_reflink_snapshot_driver_prune() -> None:
    """Test pruning older snapshots retaining only keep_count."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_path = Path(tmp_dir)
        workspace = root_path / "workspace"
        workspace.mkdir()
        storage = root_path / "snapshots"

        driver = ReflinkSnapshotDriver(storage_root=storage)
        for i in range(5):
            (workspace / f"f_{i}.txt").write_text("data", encoding="utf-8")
            await driver.create_snapshot(f"chk_{i}", workspace)

        pruned = await driver.prune_snapshots(keep_count=2)
        assert pruned == 3


@pytest.mark.asyncio
async def test_shadow_git_driver_and_factory() -> None:
    """Test ShadowGit driver and factory helper."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root_path = Path(tmp_dir)
        driver = get_default_snapshot_driver(root_path)
        assert isinstance(driver, SnapshotDriverProtocol)

        shadow_driver = ShadowGitSnapshotDriver(root_path)
        ref = await shadow_driver.create_snapshot("git_chk_01", root_path)
        assert ref.snapshot_id == "git_chk_01"
        assert await shadow_driver.restore_snapshot(ref, root_path) is True


def test_evaluate_high_impact_command_detection() -> None:
    """Test structured classification of high-impact irreversible commands."""
    # 1. Destructive commands
    is_hi, label, cat = evaluate_high_impact_command("git reset --hard HEAD~1")
    assert is_hi is True
    assert label is not None
    assert cat == "UNCOMMITTED_RESET"

    is_hi, label, cat = evaluate_high_impact_command("rm -rf /")
    assert is_hi is True
    assert cat == "WORKSPACE_PURGE"

    is_hi, label, cat = evaluate_high_impact_command("git clean -fd")
    assert is_hi is True
    assert cat == "UNCOMMITTED_RESET"

    # 2. Safe commands
    is_hi, label, cat = evaluate_high_impact_command("ls -la")
    assert is_hi is False
    assert cat == "SAFE"

    is_hi, label, cat = evaluate_high_impact_command("git status")
    assert is_hi is False
    assert cat == "SAFE"

    # 3. Preflight check raises ToolError for destructive commands
    with pytest.raises(ToolError) as exc_info:
        check_destructive_commands("git reset --hard")
    assert "destructive workspace command" in str(exc_info.value)
