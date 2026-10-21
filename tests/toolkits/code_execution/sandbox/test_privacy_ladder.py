"""Unit tests for the three-tier sandbox privacy fail-closed ladder.

Verifies:
1. Tier 1 (File-Level): Sensitive credential/secret file blocking (.env, id_rsa, keys, tokens, system dirs, devices)
2. Tier 2 (Session-Level): Session security mode enforcement (is_read_only, allow_workspace_persistence=False)
3. Tier 3 (Workspace-Level): Boundary containment, traversal, and symlink escape defense
4. Path list sanitization (validate_and_sanitize_persistence_paths)
5. Robustness to null bytes, empty paths, and case-insensitivity on macOS/Windows
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.code_execution.sandbox.privacy_ladder import (
    PrivacyLadderScope,
    PrivacyLadderViolationType,
    PrivacyTier,
    validate_and_sanitize_persistence_paths,
    validate_privacy_ladder,
)


class TestPrivacyLadder:
    """Test suite for validate_privacy_ladder pure function."""

    @pytest.fixture
    def workspace(self) -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            ws = os.path.realpath(tmpdir)
            yield ws

    def test_empty_or_invalid_path_fails_closed(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        res1 = validate_privacy_ladder("", scope, workspace)
        assert not res1.is_allowed
        assert res1.tier == PrivacyTier.TIER_1_FILE
        assert res1.violation == PrivacyLadderViolationType.EMPTY_PATH

        res2 = validate_privacy_ladder("   ", scope, workspace)
        assert not res2.is_allowed
        assert res2.violation == PrivacyLadderViolationType.EMPTY_PATH

    def test_null_byte_injection_blocked(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        res = validate_privacy_ladder("data\x00.txt", scope, workspace)
        assert not res.is_allowed
        assert res.violation == PrivacyLadderViolationType.NULL_BYTE

    def test_tier_2_readonly_session_fails_closed(self, workspace: str) -> None:
        scope = PrivacyLadderScope(is_read_only=True)
        res = validate_privacy_ladder("normal_file.txt", scope, workspace)
        assert not res.is_allowed
        assert res.tier == PrivacyTier.TIER_2_SESSION
        assert res.violation == PrivacyLadderViolationType.READONLY_SESSION_MUTATION

    def test_tier_2_persistence_disabled_fails_closed(self, workspace: str) -> None:
        scope = PrivacyLadderScope(allow_workspace_persistence=False)
        res = validate_privacy_ladder("normal_file.txt", scope, workspace)
        assert not res.is_allowed
        assert res.tier == PrivacyTier.TIER_2_SESSION
        assert res.violation == PrivacyLadderViolationType.READONLY_SESSION_MUTATION

    @pytest.mark.parametrize(
        "secret_path",
        [
            ".env",
            ".env.local",
            ".env.production",
            "server.key",
            "cert.pem",
            "id_rsa",
            "id_rsa.pub",
            "id_ed25519",
            "credentials.json",
            "secrets.json",
            "token_auth.json",
            "auth_store.json",
            "key.pfx",
            "store.kdbx",
        ],
    )
    def test_tier_1_sensitive_credential_files_blocked(self, workspace: str, secret_path: str) -> None:
        scope = PrivacyLadderScope()
        target = os.path.join(workspace, secret_path)
        res = validate_privacy_ladder(target, scope, workspace)
        assert not res.is_allowed
        assert res.tier == PrivacyTier.TIER_1_FILE
        assert res.violation == PrivacyLadderViolationType.SENSITIVE_CREDENTIAL

    @pytest.mark.parametrize(
        "dangerous_path",
        [
            "/etc/passwd",
            "/sys/kernel",
            "/proc/cpuinfo",
            "/dev/null",
        ],
    )
    def test_tier_1_dangerous_system_paths_blocked(self, workspace: str, dangerous_path: str) -> None:
        scope = PrivacyLadderScope()
        res = validate_privacy_ladder(dangerous_path, scope, workspace)
        assert not res.is_allowed
        assert res.tier == PrivacyTier.TIER_1_FILE
        assert res.violation in (
            PrivacyLadderViolationType.DANGEROUS_SYSTEM_PATH,
            PrivacyLadderViolationType.BLOCKED_DEVICE,
            PrivacyLadderViolationType.WORKSPACE_ESCAPE,
        )

    def test_tier_1_blocked_device_paths(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        res = validate_privacy_ladder("CON", scope, workspace)
        assert not res.is_allowed
        assert res.tier == PrivacyTier.TIER_1_FILE
        assert res.violation == PrivacyLadderViolationType.BLOCKED_DEVICE

    def test_tier_3_workspace_escape_blocked(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        # Relative traversal
        escape_path = os.path.join(workspace, "../../outside.txt")
        res1 = validate_privacy_ladder(escape_path, scope, workspace)
        assert not res1.is_allowed
        assert res1.tier == PrivacyTier.TIER_3_WORKSPACE
        assert res1.violation == PrivacyLadderViolationType.WORKSPACE_ESCAPE

        # Unrelated absolute path
        res2 = validate_privacy_ladder("/tmp/unrelated/file.txt", scope, workspace)
        assert not res2.is_allowed
        assert res2.tier == PrivacyTier.TIER_3_WORKSPACE
        assert res2.violation == PrivacyLadderViolationType.WORKSPACE_ESCAPE

    def test_tier_3_symlink_escape_blocked(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        outside_dir = tempfile.mkdtemp()
        try:
            outside_file = os.path.join(outside_dir, "secret_outside.txt")
            Path(outside_file).write_text("classified")

            link_in_ws = os.path.join(workspace, "escape_link")
            os.symlink(outside_file, link_in_ws)

            res = validate_privacy_ladder(link_in_ws, scope, workspace)
            assert not res.is_allowed
            assert res.tier == PrivacyTier.TIER_3_WORKSPACE
            assert res.violation == PrivacyLadderViolationType.WORKSPACE_ESCAPE
        finally:
            import shutil
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_valid_workspace_files_allowed(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        valid_paths = [
            "report.xlsx",
            "clean_data.py",
            "subfolder/analysis.csv",
            "dist/bundle.js",
            "docs/README.md",
        ]
        for rel_p in valid_paths:
            full_p = os.path.join(workspace, rel_p)
            res = validate_privacy_ladder(full_p, scope, workspace)
            assert res.is_allowed
            assert res.tier is None
            assert res.violation is None

    def test_validate_and_sanitize_persistence_paths(self, workspace: str) -> None:
        scope = PrivacyLadderScope()
        candidates = [
            os.path.join(workspace, "valid_report.xlsx"),
            os.path.join(workspace, ".env"),
            os.path.join(workspace, "script.py"),
            os.path.join(workspace, "client.key"),
            "/etc/shadow",
            os.path.join(workspace, "../outside.txt"),
        ]

        sanitized = validate_and_sanitize_persistence_paths(candidates, scope, workspace)
        assert len(sanitized) == 2
        assert os.path.join(workspace, "valid_report.xlsx") in sanitized
        assert os.path.join(workspace, "script.py") in sanitized
