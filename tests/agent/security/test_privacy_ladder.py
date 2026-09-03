"""Unit tests for PrivacyFailClosedLadder (3-level hierarchy).

Tests:
- Level 3 (Workspace-level): Workspace boundary escaping, dangerous system paths, blocked devices
- Level 2 (Session-level): Session sensitivity ceiling enforcement (S1/S2/S3)
- Level 1 (File-level): Restricted patterns, unencrypted S3 confidential personal data and credentials
- Assert valid raises PrivacyFailClosedViolationError with rich diagnostic metadata
"""

import pytest

from myrm_agent_harness.core.security.guards.privacy_ladder import (
    PrivacyFailClosedLadder,
    PrivacyFailClosedViolationError,
    PrivacyLadderLevel,
    PrivacyLadderViolationType,
    PrivacyScope,
)
from myrm_agent_harness.core.security.types import SensitivityLevel


def test_level3_workspace_enclosed_allowed(tmp_path):
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    target_file = str(tmp_path / "workspace" / "app.py")

    scope = PrivacyScope(workspace_root=workspace)
    verdict = PrivacyFailClosedLadder.evaluate(
        target_path=target_file,
        content="print('hello world')",
        scope=scope,
    )
    assert verdict.is_allowed is True
    assert verdict.level is None
    assert verdict.violation_type is None


def test_level3_workspace_boundary_escaped(tmp_path):
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    target_file = str(tmp_path / "other" / "secret.txt")

    scope = PrivacyScope(workspace_root=workspace)
    verdict = PrivacyFailClosedLadder.evaluate(
        target_path=target_file,
        content="data",
        scope=scope,
    )
    assert verdict.is_allowed is False
    assert verdict.level == PrivacyLadderLevel.WORKSPACE
    assert verdict.violation_type == PrivacyLadderViolationType.WORKSPACE_BOUNDARY_ESCAPED
    assert "escapes authorized workspace" in verdict.reason


def test_level3_dangerous_system_path():
    verdict = PrivacyFailClosedLadder.evaluate(
        target_path="/etc/passwd",
        content="root:x:0:0::/root:/bin/bash",
    )
    assert verdict.is_allowed is False
    assert verdict.level == PrivacyLadderLevel.WORKSPACE
    assert verdict.violation_type == PrivacyLadderViolationType.DANGEROUS_SYSTEM_PATH


def test_level3_blocked_device_path():
    verdict = PrivacyFailClosedLadder.evaluate(
        target_path="/dev/null",
        content="test",
    )
    assert verdict.is_allowed is False
    assert verdict.level == PrivacyLadderLevel.WORKSPACE
    assert verdict.violation_type in (
        PrivacyLadderViolationType.BLOCKED_DEVICE,
        PrivacyLadderViolationType.DANGEROUS_SYSTEM_PATH,
    )


def test_level2_session_sensitivity_exceeded(tmp_path):
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    target_file = str(tmp_path / "workspace" / "report.txt")

    scope = PrivacyScope(
        workspace_root=workspace,
        max_allowed_sensitivity=SensitivityLevel.S1,
    )
    verdict = PrivacyFailClosedLadder.evaluate(
        target_path=target_file,
        content="normal report",
        scope=scope,
        session_turn_level=SensitivityLevel.S2,
    )
    assert verdict.is_allowed is False
    assert verdict.level == PrivacyLadderLevel.SESSION
    assert verdict.violation_type == PrivacyLadderViolationType.SESSION_SENSITIVITY_EXCEEDED
    assert "exceeds maximum allowed privacy ceiling" in verdict.reason


def test_level1_restricted_pattern(tmp_path):
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    target_file = str(tmp_path / "workspace" / "server.pem")

    scope = PrivacyScope(workspace_root=workspace)
    verdict = PrivacyFailClosedLadder.evaluate(
        target_path=target_file,
        content="certificate data",
        scope=scope,
    )
    assert verdict.is_allowed is False
    assert verdict.level == PrivacyLadderLevel.FILE
    assert verdict.violation_type == PrivacyLadderViolationType.RESTRICTED_FILE_MODIFICATION


def test_level1_unencrypted_s3_confidential(tmp_path):
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    target_file = str(tmp_path / "workspace" / "users.json")

    # Content with Password context (S3)
    s3_content = "database_password = 'SuperSecretPassword123!'"
    scope = PrivacyScope(workspace_root=workspace, allow_s3_persistence=False)

    verdict = PrivacyFailClosedLadder.evaluate(
        target_path=target_file,
        content=s3_content,
        scope=scope,
    )
    assert verdict.is_allowed is False
    assert verdict.level == PrivacyLadderLevel.FILE
    assert verdict.violation_type == PrivacyLadderViolationType.UNENCRYPTED_S3_CONFIDENTIAL



def test_assert_valid_raises_fail_closed_exception(tmp_path):
    workspace = str(tmp_path / "workspace")
    (tmp_path / "workspace").mkdir()
    target_file = str(tmp_path / "unauthorized" / "dump.sql")

    scope = PrivacyScope(workspace_root=workspace)
    with pytest.raises(PrivacyFailClosedViolationError) as exc_info:
        PrivacyFailClosedLadder.assert_valid(
            target_path=target_file,
            content="select 1",
            scope=scope,
        )
    assert exc_info.value.verdict.level == PrivacyLadderLevel.WORKSPACE
    assert exc_info.value.target_path == target_file
