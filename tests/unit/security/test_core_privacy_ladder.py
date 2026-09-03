"""Unit tests for PrivacyLadderValidator (3-level fail-closed privacy ladder)."""

from __future__ import annotations

import os
from pathlib import Path

from myrm_agent_harness.core.security.privacy import (
    PrivacyLadderLevel,
    PrivacyLadderValidator,
    PrivacyScanVerdict,
)


def test_level_3_workspace_root_confinement(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")

    validator = PrivacyLadderValidator(workspace_root=workspace, session_id="sess_123")

    # Inside file is safe
    inside_file = workspace / "test.txt"
    inside_file.write_text("hello")
    res_inside = validator.evaluate_path(inside_file)
    assert res_inside.verdict == PrivacyScanVerdict.PASS
    assert res_inside.sanitized_rel_path == "test.txt"

    # Outside file fails level 3
    res_outside = validator.evaluate_path(outside)
    assert res_outside.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.WORKSPACE_LEVEL for v in res_outside.violations)

    # Relative path traversal fails level 3
    res_traversal = validator.evaluate_path("../outside.txt")
    assert res_traversal.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.WORKSPACE_LEVEL for v in res_traversal.violations)


def test_level_2_session_isolation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    sess_1_dir = workspace / "sessions" / "sess_1"
    sess_2_dir = workspace / "sessions" / "sess_2"
    sess_1_dir.mkdir(parents=True)
    sess_2_dir.mkdir(parents=True)

    validator_sess_1 = PrivacyLadderValidator(workspace_root=workspace, session_id="sess_1")

    # Accessing own session directory
    res_own = validator_sess_1.evaluate_path("sessions/sess_1/output.csv")
    assert res_own.verdict == PrivacyScanVerdict.PASS

    # Accessing another session directory
    res_other = validator_sess_1.evaluate_path("sessions/sess_2/stolen.csv")
    assert res_other.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.SESSION_LEVEL for v in res_other.violations)


def test_level_1_sensitive_files_and_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    validator = PrivacyLadderValidator(workspace_root=workspace, session_id="sess_123")

    # .env files are blocked
    res_env = validator.evaluate_path(".env")
    assert res_env.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.FILE_LEVEL for v in res_env.violations)

    # id_rsa is blocked
    res_rsa = validator.evaluate_path("keys/id_rsa")
    assert res_rsa.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.FILE_LEVEL for v in res_rsa.violations)

    # System roots are blocked
    res_sys = validator.evaluate_path("/etc/passwd")
    assert res_sys.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.FILE_LEVEL for v in res_sys.violations)


def test_ignored_transient_cache_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    validator = PrivacyLadderValidator(workspace_root=workspace, session_id="sess_123")

    res_pycache = validator.evaluate_path("__pycache__/compiled.pyc")
    assert res_pycache.verdict == PrivacyScanVerdict.IGNORED
    assert res_pycache.is_ignored is True

    res_nodemodules = validator.evaluate_path("node_modules/package/index.js")
    assert res_nodemodules.verdict == PrivacyScanVerdict.IGNORED


def test_edge_cases_and_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret_dir = tmp_path / "secret_data"
    secret_dir.mkdir()
    secret_file = secret_dir / "confidential.txt"
    secret_file.write_text("top_secret")

    # Symlink inside workspace pointing outside
    symlink_target = workspace / "sym_link_escape"
    try:
        os.symlink(secret_dir, symlink_target)
    except OSError:
        return

    validator = PrivacyLadderValidator(workspace_root=workspace, session_id="sess_123")

    # Evaluating the symlinked directory path
    res_symlink = validator.evaluate_path("sym_link_escape/confidential.txt")
    assert res_symlink.verdict == PrivacyScanVerdict.FAIL_CLOSED
    assert any(v.level == PrivacyLadderLevel.WORKSPACE_LEVEL for v in res_symlink.violations)

    # Empty string path
    res_empty = validator.evaluate_path("   ")
    assert res_empty.verdict == PrivacyScanVerdict.FAIL_CLOSED


def test_custom_patterns(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    validator = PrivacyLadderValidator(
        workspace_root=workspace,
        custom_ignore_files=("*.custom_cache",),
    )
    res_custom = validator.evaluate_path("data.custom_cache")
    assert res_custom.verdict == PrivacyScanVerdict.IGNORED
