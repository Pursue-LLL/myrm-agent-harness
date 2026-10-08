"""
[POS] tests/unit/test_host_execution_guard_suite.py
[INPUT] pytest, tmp_path, myrm_agent_harness.core.security.host_execution_guard
[OUTPUT] Unit tests for HostExecutionGuardSuite

Validates path protection and virtual overlay redirection, destructive command AST inspection,
and workspace copy-on-write snapshotting and atomic rollback.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.core.security.host_execution_guard import (
    DestructiveRiskLevel,
    HostExecutionGuardSuite,
    PathAccessMode,
    PathProtectionAction,
)


def test_path_shield_system_protection_and_virtual_overlay(tmp_path: Path) -> None:
    """Validate mechanical protection of system paths and transparent scratch overlay redirection."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    scratch = tmp_path / "scratch_overlay"
    scratch.mkdir()

    # 1. Without scratch overlay: write to /etc/hosts is strictly blocked
    suite_strict = HostExecutionGuardSuite(workspace_root=str(workspace))
    res_block = suite_strict.inspect_path("/etc/hosts", mode=PathAccessMode.WRITE)
    assert res_block.is_protected is True
    assert res_block.action == PathProtectionAction.BLOCK
    assert "strictly blocked" in res_block.explanation

    # 2. With scratch overlay: write to /usr/local/bin is redirected
    suite_overlay = HostExecutionGuardSuite(
        workspace_root=str(workspace),
        scratch_overlay_dir=str(scratch),
    )
    res_redirect = suite_overlay.inspect_path("/usr/local/bin/my_tool", mode=PathAccessMode.WRITE)
    assert res_redirect.is_protected is True
    assert res_redirect.action == PathProtectionAction.VIRTUAL_OVERLAY
    assert str(scratch) in res_redirect.effective_path

    # 3. Read access to user credentials (~/.ssh/id_rsa) is blocked
    res_cred = suite_overlay.inspect_path("~/.ssh/id_rsa", mode=PathAccessMode.READ)
    assert res_cred.action == PathProtectionAction.BLOCK
    assert "confidential user credential store" in res_cred.explanation

    # 4. Write inside authorized workspace root is allowed
    target_file = workspace / "src" / "app.py"
    res_ws = suite_overlay.inspect_path(str(target_file), mode=PathAccessMode.WRITE)
    assert res_ws.action == PathProtectionAction.ALLOW
    assert res_ws.is_protected is False


def test_destructive_ast_guard_blocked_and_hitl() -> None:
    """Validate AST-level detection of catastrophic and high-risk shell commands."""
    suite = HostExecutionGuardSuite()

    # 1. Catastrophic commands blocked immediately
    catastrophic_commands = [
        "rm -rf /",
        "rm -rf ~",
        "rm -rf /etc",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda",
        "chmod -R 777 /",
    ]
    for cmd in catastrophic_commands:
        res = suite.inspect_command(cmd)
        assert res.risk_level == DestructiveRiskLevel.BLOCKED_DESTRUCTIVE
        assert res.is_blocked is True
        assert res.requires_hitl is False

    # 2. High-risk commands requiring HITL approval
    hitl_commands = [
        "rm -rf ./build_cache",
        "iptables -F",
        "systemctl stop nginx",
        "reboot",
    ]
    for cmd in hitl_commands:
        res = suite.inspect_command(cmd)
        assert res.risk_level == DestructiveRiskLevel.REQUIRE_HITL
        assert res.requires_hitl is True
        assert res.is_blocked is False

    # 3. Safe commands allowed without friction
    safe_commands = [
        "git status",
        "npm test",
        "pytest -v tests/",
        "python3 -m build",
        "cat README.md",
    ]
    for cmd in safe_commands:
        res = suite.inspect_command(cmd)
        assert res.risk_level == DestructiveRiskLevel.SAFE
        assert res.is_blocked is False
        assert res.requires_hitl is False


def test_command_approval_and_rejection_lifecycle() -> None:
    """Validate HITL operator approval and rejection lifecycle."""
    suite = HostExecutionGuardSuite()

    # 1. Command requires HITL
    insp = suite.inspect_command("rm -rf ./node_modules")
    assert insp.requires_hitl is True
    assert len(suite.list_pending_commands()) == 1

    # 2. Operator approves
    approved = suite.approve_command(insp.inspection_id)
    assert approved.risk_level == DestructiveRiskLevel.SAFE
    assert approved.is_blocked is False
    assert len(suite.list_pending_commands()) == 0

    # 3. Operator rejects another command
    insp2 = suite.inspect_command("ufw disable")
    rejected = suite.reject_command(insp2.inspection_id)
    assert rejected.risk_level == DestructiveRiskLevel.BLOCKED_DESTRUCTIVE
    assert rejected.is_blocked is True


def test_workspace_cow_vault_snapshot_and_rollback(tmp_path: Path) -> None:
    """Validate Copy-on-Write snapshot capture and sub-second atomic rollback."""
    suite = HostExecutionGuardSuite(workspace_root=str(tmp_path))

    file1 = tmp_path / "main.py"
    file1.write_text("print('version 1.0')\n", encoding="utf-8")
    file2_rel = "utils.py"

    # 1. Capture snapshot before modifications
    snapshot = suite.create_workspace_snapshot(
        workspace_root=str(tmp_path),
        target_rel_paths=("main.py", file2_rel),
        description="Before dangerous agent edits",
    )
    assert snapshot.is_restored is False
    assert len(snapshot.entries) == 2

    # 2. Agent corrupts main.py and creates utils.py
    file1.write_text("SYNTAX_ERROR_CORRUPTED_CODE\n", encoding="utf-8")
    file2 = tmp_path / file2_rel
    file2.write_text("def unwanted_func(): pass\n", encoding="utf-8")

    assert "CORRUPTED" in file1.read_text(encoding="utf-8")
    assert file2.exists()

    # 3. Execute atomic rollback
    restored = suite.rollback_workspace_snapshot(snapshot.snapshot_id)
    assert restored.is_restored is True

    # 4. Verify main.py restored and file2 deleted
    assert file1.read_text(encoding="utf-8") == "print('version 1.0')\n"
    assert not file2.exists()


def test_metrics_tracking(tmp_path: Path) -> None:
    """Validate cumulative metrics tracking."""
    suite = HostExecutionGuardSuite(workspace_root=str(tmp_path))

    suite.inspect_path("/etc/passwd", mode=PathAccessMode.WRITE)
    suite.inspect_command("rm -rf /")
    insp = suite.inspect_command("rm -rf temp/")
    suite.approve_command(insp.inspection_id)

    file_tmp = tmp_path / "test.txt"
    file_tmp.write_text("initial\n", encoding="utf-8")
    snap = suite.create_workspace_snapshot(str(tmp_path), ("test.txt",))
    suite.rollback_workspace_snapshot(snap.snapshot_id)

    metrics = suite.metrics
    assert metrics.paths_inspected_total == 1
    assert metrics.paths_blocked_total == 1
    assert metrics.commands_inspected_total == 2
    assert metrics.commands_blocked_total == 1
    assert metrics.hitl_requested_total == 1
    assert metrics.hitl_approved_total == 1
    assert metrics.snapshots_created_total == 1
    assert metrics.rollbacks_executed_total == 1
