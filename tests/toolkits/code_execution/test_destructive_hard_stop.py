"""Unit tests for Irreversible Destructive Action Hard Stop Line and Workspace Snapshot Suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

from myrm_agent_harness.toolkits.code_execution.security.ast_parser import (
    BashASTParser,
    CapabilityLevel,
)
from myrm_agent_harness.toolkits.code_execution.security.workspace_snapshot import (
    create_workspace_snapshot,
    rollback_workspace_snapshot,
)


class TestDestructiveActionClassification:
    """Test classification of irreversible destructive commands."""

    def test_rm_recursive_deletions(self) -> None:
        """Verify rm -rf and recursive variants are classified as IRREVERSIBLE_DESTRUCTIVE."""
        commands = [
            "rm -rf /",
            "rm -r -f ./src",
            "rm -fr /workspace/build",
            "rm --recursive --force node_modules",
            "rm -rf ./*",
            "rm -rf $TEMP_DIR/*",
            "rm -r src/",
            "rm -R old_dir",
        ]
        for cmd in commands:
            actions = BashASTParser.parse(cmd)
            assert len(actions) == 1, f"Failed for {cmd}"
            assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE, f"Failed for {cmd}"
            assert actions[0].escalation_reason == "recursive_file_deletion", f"Failed for {cmd}"

    def test_rm_safe_single_file_not_destructive(self) -> None:
        """Verify standard single file removals without recursive flags are not marked IRREVERSIBLE_DESTRUCTIVE."""
        safe_commands = [
            "rm file.txt",
            "rm -v temp.log",
            "rm doc1.md doc2.md",
        ]
        for cmd in safe_commands:
            actions = BashASTParser.parse(cmd)
            assert len(actions) == 1
            assert actions[0].capability_level == CapabilityLevel.WORKSPACE_MUTATION

    def test_git_destructive_subcommands(self) -> None:
        """Verify git reset --hard, clean -fdx, push --force, branch -D are IRREVERSIBLE_DESTRUCTIVE."""
        destructive_git_cases = [
            ("git reset --hard HEAD~1", "git_hard_reset"),
            ("git clean -fdx", "git_untracked_clean"),
            ("git clean -f", "git_untracked_clean"),
            ("git push --force origin main", "git_force_push"),
            ("git push -f origin main", "git_force_push"),
            ("git branch -D obsolete_feature", "git_force_branch_delete"),
            ("git checkout -f", "git_force_checkout"),
        ]
        for cmd, expected_reason in destructive_git_cases:
            actions = BashASTParser.parse(cmd)
            assert len(actions) == 1, f"Failed for {cmd}"
            assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE, f"Failed for {cmd}"
            assert actions[0].escalation_reason == expected_reason, f"Failed for {cmd}"

    def test_git_non_destructive_not_misclassified(self) -> None:
        """Verify standard git push, commit, status are NOT marked IRREVERSIBLE_DESTRUCTIVE."""
        actions = BashASTParser.parse("git push origin main")
        assert len(actions) == 1
        assert actions[0].capability_level == CapabilityLevel.CAPABILITY_ESCALATION
        assert actions[0].escalation_reason == "git_remote_sync"

        actions2 = BashASTParser.parse("git commit -m 'feat: test'")
        assert len(actions2) == 1
        assert actions2[0].capability_level == CapabilityLevel.WORKSPACE_MUTATION

    def test_system_destructive_tools(self) -> None:
        """Verify mkfs, dd, wipefs are marked IRREVERSIBLE_DESTRUCTIVE."""
        sys_cases = [
            "mkfs.ext4 /dev/sdb1",
            "fdisk /dev/sda",
            "wipefs -a /dev/nvme0n1",
            "dd if=/dev/zero of=/dev/sda bs=1M",
        ]
        for cmd in sys_cases:
            actions = BashASTParser.parse(cmd)
            assert len(actions) == 1
            assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE

    def test_redirection_disk_overwrite(self) -> None:
        """Verify redirection targeting raw devices is caught as IRREVERSIBLE_DESTRUCTIVE."""
        actions = BashASTParser.parse("echo 'corrupt' > /dev/sda")
        assert len(actions) == 1
        assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE

    def test_find_destructive_variants(self) -> None:
        """Verify find with -delete, -exec rm, or -ok rm is caught as IRREVERSIBLE_DESTRUCTIVE."""
        find_cases = [
            ("find . -name '*.tmp' -delete", "find_bulk_deletion"),
            ("find /var/log -type f -exec rm -rf {} +", "find_bulk_deletion"),
            ("find . -type f -ok rm {} \\;", "find_bulk_deletion"),
        ]
        for cmd, expected_reason in find_cases:
            actions = BashASTParser.parse(cmd)
            assert len(actions) == 1, f"Failed for {cmd}"
            assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE, f"Failed for {cmd}"
            assert actions[0].escalation_reason == expected_reason, f"Failed for {cmd}"

        # Safe find should not be marked destructive
        safe_find = BashASTParser.parse("find . -name '*.py'")
        assert len(safe_find) == 1
        assert safe_find[0].capability_level != CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE

    def test_inline_script_destruction(self) -> None:
        """Verify inline python and node scripts invoking deletion APIs are caught."""
        script_cases = [
            ('python -c "import shutil; shutil.rmtree(\'/tmp/cache\')"', "python_inline_file_destruction"),
            ('python3 -c "import os; os.remove(\'secret.key\')"', "python_inline_file_destruction"),
            ('node -e "require(\'fs\').rmSync(\'/var/data\', { recursive: true })"', "node_inline_file_destruction"),
            ('bun -e "import fs from \'fs\'; fs.unlinkSync(\'db.sqlite\')"', "node_inline_file_destruction"),
        ]
        for cmd, expected_reason in script_cases:
            actions = BashASTParser.parse(cmd)
            assert len(actions) == 1, f"Failed for {cmd}"
            assert actions[0].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE, f"Failed for {cmd}"
            assert actions[0].escalation_reason == expected_reason, f"Failed for {cmd}"

        # Safe inline script should not be marked destructive
        safe_script = BashASTParser.parse('python -c "print(\'hello\')"')
        assert len(safe_script) == 1
        assert safe_script[0].capability_level != CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE

    def test_compound_commands_with_destruction(self) -> None:
        """Verify compound pipeline correctly identifies the destructive sub-action."""
        cmd = "echo 'starting' && rm -rf ./cache && echo 'done'"
        actions = BashASTParser.parse(cmd)
        assert len(actions) == 3
        assert actions[0].capability_level == CapabilityLevel.SAFE_READONLY
        assert actions[1].capability_level == CapabilityLevel.IRREVERSIBLE_DESTRUCTIVE
        assert actions[2].capability_level == CapabilityLevel.SAFE_READONLY
        assert BashASTParser.has_destructive(actions) is True
        assert len(BashASTParser.get_escalation_actions(actions)) == 1


class TestWorkspaceSnapshotAndRollback:
    """Test zero-copy atomic workspace snapshot creation and rollback."""

    def test_snapshot_non_git_workspace_graceful_degrade(self, tmp_path: Path) -> None:
        """Non-git workspace returns graceful degrade result without raising error."""
        non_git_dir = tmp_path / "plain_dir"
        non_git_dir.mkdir()
        res = create_workspace_snapshot(non_git_dir)
        assert res.success is False
        assert res.is_git_repository is False
        assert res.snapshot_id is None
        assert "not a Git repository" in (res.error_message or "")

    def test_snapshot_and_rollback_in_git_workspace(self, tmp_path: Path) -> None:
        """Verify snapshot captures working tree and rollback cleanly restores it."""
        repo_dir = tmp_path / "test_repo"
        repo_dir.mkdir()
        # Initialize Git repo
        subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.com"], cwd=str(repo_dir), capture_output=True, check=True)

        # Create initial committed file
        test_file = repo_dir / "app.py"
        test_file.write_text("print('v1')")
        subprocess.run(["git", "add", "app.py"], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(repo_dir), capture_output=True, check=True)

        # Mutate file (uncommitted dirty state)
        test_file.write_text("print('v2-uncommitted')")

        # Create snapshot prior to destructive command
        snapshot_res = create_workspace_snapshot(repo_dir)
        assert snapshot_res.success is True
        assert snapshot_res.is_git_repository is True
        assert snapshot_res.snapshot_id is not None
        assert snapshot_res.duration_ms < 500.0  # Fast

        # Simulate destructive command (e.g. file wiped or corrupted)
        test_file.write_text("corrupted content")
        assert test_file.read_text() == "corrupted content"

        # Execute rollback
        rolled_back = rollback_workspace_snapshot(repo_dir, snapshot_res.snapshot_id)
        assert rolled_back is True
        assert test_file.read_text() == "print('v2-uncommitted')"
