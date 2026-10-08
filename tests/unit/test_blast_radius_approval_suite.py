"""
[POS] tests/unit/test_blast_radius_approval_suite.py
Unit tests for Approval Card Blast Radius Dry-Run Impact Preview & Typed Launch Codes Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.blast_radius_approval import (
    BlastRadiusApprovalFacade,
    ImpactTargetType,
)


@pytest.fixture
def facade() -> BlastRadiusApprovalFacade:
    return BlastRadiusApprovalFacade()


def test_safe_read_only_command_approval(
    facade: BlastRadiusApprovalFacade,
) -> None:
    policy = facade.evaluate_command_approval("cat README.md")

    assert policy.command == "cat README.md"
    assert policy.is_destructive is False
    assert policy.never_folded is False
    assert policy.impact_preview is None
    assert policy.launch_code is None
    assert "Enter" in policy.allowed_shortcuts
    assert "y" in policy.allowed_shortcuts


def test_destructive_filesystem_rm_impact_preview(
    facade: BlastRadiusApprovalFacade,
) -> None:
    policy = facade.evaluate_command_approval("rm -rf /tmp/test_dir/*.log")

    assert policy.is_destructive is True
    assert policy.never_folded is True
    assert policy.impact_preview is not None
    assert policy.impact_preview.estimated_files_count >= 1
    assert "Will delete" in policy.impact_preview.summary

    targets = policy.impact_preview.targets
    assert len(targets) >= 1
    assert targets[0].action == "delete"
    assert targets[0].target_type in (ImpactTargetType.FILE, ImpactTargetType.DIRECTORY)


def test_typed_launch_code_lifecycle(
    facade: BlastRadiusApprovalFacade,
) -> None:
    # 1. Force push requires challenge
    cmd = "git push --force origin main"
    policy = facade.evaluate_command_approval(cmd)

    assert policy.is_destructive is True
    assert policy.never_folded is True
    assert policy.launch_code is not None
    assert policy.launch_code.requires_challenge is True

    token = policy.launch_code.challenge_token
    assert token is not None
    assert len(token) == 6
    # Enter is omitted to prevent accidental blind approval
    assert "Enter" not in policy.allowed_shortcuts
    assert "Esc" in policy.allowed_shortcuts

    # 2. Verify with incorrect input
    ok_fail, reason_fail = facade.verify_launch_code(token, "WRONG123")
    assert ok_fail is False
    assert "mismatch" in reason_fail.lower()

    # 3. Verify with correct input
    ok_succ, reason_succ = facade.verify_launch_code(token, token)
    assert ok_succ is True
    assert "verified" in reason_succ.lower()

    # 4. Anti-replay verification: token cannot be reused
    ok_replay, reason_replay = facade.verify_launch_code(token, token)
    assert ok_replay is False
    assert "already been consumed" in reason_replay.lower()


def test_never_fold_batch_grouping(
    facade: BlastRadiusApprovalFacade,
) -> None:
    commands = [
        ("span-01", "echo 'hello world'"),
        ("span-02", "rm -rf /tmp/data"),
        ("span-03", "ls -la"),
    ]

    policies, groups = facade.evaluate_batch_spans(commands)

    assert len(policies) == 3
    # Destructive span-02 must be isolated in its own single-element group
    assert ["span-02"] in groups
    # Non-destructive spans (span-01, span-03) are grouped together
    assert ["span-01", "span-03"] in groups

    p_dest = next(p for p in policies if p.span_id == "span-02")
    assert p_dest.never_folded is True
    assert p_dest.is_destructive is True

    p_safe = next(p for p in policies if p.span_id == "span-01")
    assert p_safe.never_folded is False
    assert p_safe.is_destructive is False


def test_sql_destructive_query_preview(
    facade: BlastRadiusApprovalFacade,
) -> None:
    cmd = "DROP TABLE audit_logs;"
    policy = facade.evaluate_command_approval(cmd)

    assert policy.is_destructive is True
    assert policy.never_folded is True
    assert policy.impact_preview is not None
    assert "Database destruction" in policy.impact_preview.summary
    assert policy.impact_preview.targets[0].path_or_identifier == "audit_logs"
    assert policy.impact_preview.targets[0].target_type == ImpactTargetType.DATABASE_TABLE
