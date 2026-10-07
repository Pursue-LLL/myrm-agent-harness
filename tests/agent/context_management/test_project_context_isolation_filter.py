# ============================================================================
# Unit Tests for CrossProjectSessionContextIsolationAndObjectiveRecap (Item 145)
# Verifies project boundary check, alien path screening, ambiguous prompt
# detection, and objective recap alignment gate interception.
# ============================================================================

import os

from myrm_agent_harness.agent.context_management.isolation import (
    ObjectiveRecapStatus,
    ProjectBoundary,
    ProjectContextIsolationFilter,
)


def test_project_boundary_path_validation() -> None:
    """Verifies internal vs external path containment check."""
    root = "/tmp/workspace/project-alpha"
    boundary = ProjectBoundary(project_id="proj-alpha", workspace_root=root)

    assert boundary.is_path_within_boundary("/tmp/workspace/project-alpha/src/main.py")
    assert boundary.is_path_within_boundary("/tmp/workspace/project-alpha/README.md")
    assert boundary.is_path_within_boundary("/tmp/workspace/project-alpha")

    # Outside paths
    assert not boundary.is_path_within_boundary("/tmp/workspace/project-beta/config.yaml")
    assert not boundary.is_path_within_boundary("/etc/passwd")
    assert not boundary.is_path_within_boundary("/tmp/workspace/project-alpha-extra/file.py")


def test_filter_cross_project_files() -> None:
    """Verifies separation of alien paths and preservation of local paths."""
    boundary = ProjectBoundary(project_id="proj-billing", workspace_root="/app/services/billing")
    guard = ProjectContextIsolationFilter()

    candidates = [
        "/app/services/billing/models.py",
        "/app/services/billing/tests/test_pay.py",
        "/app/services/auth/jwt.py",  # Alien path
        "/var/log/syslog",  # Alien path
    ]

    res = guard.filter_cross_project_files(boundary, candidates)
    assert not res.is_aligned
    assert len(res.filtered_file_paths) == 2
    assert "/app/services/auth/jwt.py" in res.filtered_file_paths
    assert len(res.retained_file_paths) == 2
    assert "/app/services/billing/models.py" in res.retained_file_paths
    assert "Detected 2 file references outside workspace" in (res.violation_reason or "")


def test_ambiguous_continuation_detection() -> None:
    """Tests identification of fuzzy continuation phrases."""
    guard = ProjectContextIsolationFilter()

    # Ambiguous phrases
    assert guard.is_ambiguous_continuation_prompt("继续刚才的修复")
    assert guard.is_ambiguous_continuation_prompt("接着优化")
    assert guard.is_ambiguous_continuation_prompt("按刚才说的做")
    assert guard.is_ambiguous_continuation_prompt("continue previous task")
    assert guard.is_ambiguous_continuation_prompt("resume with last prompt")

    # Explicit, non-ambiguous phrases
    assert not guard.is_ambiguous_continuation_prompt("在 user.py 中添加字段 email")
    assert not guard.is_ambiguous_continuation_prompt("运行 pytest 测试套件")
    assert not guard.is_ambiguous_continuation_prompt("")


def test_objective_alignment_gate_interception() -> None:
    """Tests mismatch interception when cwd does not match session project boundary."""
    boundary = ProjectBoundary(
        project_id="proj-finance",
        workspace_root="/data/repos/finance-core",
        project_name="Finance Core",
    )
    guard = ProjectContextIsolationFilter()

    # Current CWD is alienated (switched to another project)
    foreign_cwd = "/data/repos/auth-service"
    assertion = guard.assert_objective_alignment(
        boundary=boundary,
        current_cwd=foreign_cwd,
        prompt="继续刚才的优化",
        current_objective="升级支付通道重试机制",
    )

    assert assertion.status == ObjectiveRecapStatus.MISMATCH_INTERCEPTED
    assert assertion.is_blocked
    assert assertion.warning_message is not None
    assert "跨项目安全阻断" in assertion.warning_message
    assert "proj-finance" in assertion.warning_message


def test_objective_alignment_gate_verified_recap() -> None:
    """Tests verified objective recap generation under aligned cwd with fuzzy continuation."""
    root = os.path.abspath("/data/repos/finance-core")
    boundary = ProjectBoundary(
        project_id="proj-finance",
        workspace_root=root,
    )
    guard = ProjectContextIsolationFilter()

    assertion = guard.assert_objective_alignment(
        boundary=boundary,
        current_cwd=root,
        prompt="继续刚才的任务",
        current_objective="升级支付通道重试机制",
    )

    assert assertion.status == ObjectiveRecapStatus.VERIFIED
    assert not assertion.is_blocked
    assert "🎯 [当前项目目标对齐]" in assertion.recap_display_badge
    assert "升级支付通道重试机制" in assertion.recap_display_badge


def test_sanitize_alien_paths_in_text() -> None:
    """Verifies that alien paths in text prompt or context are safely redacted."""
    boundary = ProjectBoundary(project_id="p1", workspace_root="/projects/my-web")
    guard = ProjectContextIsolationFilter()

    alien = ["/other/project/secret.key", "/var/data/dump.sql"]
    raw_text = "Please examine /other/project/secret.key and /projects/my-web/index.html."

    sanitized = guard.sanitize_alien_paths_in_text(boundary, raw_text, alien)
    assert "/other/project/secret.key" not in sanitized
    assert "[CROSS_PROJECT_REDACTED: secret.key]" in sanitized
    assert "/projects/my-web/index.html" in sanitized
