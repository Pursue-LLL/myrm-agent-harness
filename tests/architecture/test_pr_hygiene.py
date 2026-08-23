"""Architecture gate: PR & Issue quality and hygiene gate assertion test.

Asserts that:
1. Conventional Commits title format parser accepts valid formats and rejects invalid ones.
2. PR body completeness parser identifies present/missing sections and sparse content.
3. Repository root contains valid PR template and Issue form configurations.
4. Issue templates have valid metadata and structured questions.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.check_pr_hygiene import (
    validate_issue_templates,
    validate_pr_body,
    validate_pr_title,
)


@pytest.mark.architecture
def test_pr_title_conventional_commits_validation() -> None:
    """Ensure PR title validator enforces conventional commits rules."""
    # Valid titles
    valid_titles = [
        "feat(desktop): add sidecar cascade process watcher",
        "fix(server): resolve token refresh timeout in stream session",
        "docs(harness): update tool layers documentation",
        "perf(frontend): memoize token chart rendering",
        "refactor(core): extract env dependency validator",
        "ci(workflows): add pr quality hygiene gate",
        "chore: bump dependencies to latest",
        "feat(harness)!: breaking change to tool signature",
    ]
    for title in valid_titles:
        res = validate_pr_title(title)
        assert res.is_valid, f"Expected '{title}' to be valid, got errors: {res.errors}"

    # Invalid titles
    invalid_titles = [
        "",
        "   ",
        "fix bug",
        "update code",
        "WIP",
        "unknown(scope): invalid type name",
        "feat(): empty scope parentheses",
        "feat: ab",  # description too short (<5 chars)
    ]
    for title in invalid_titles:
        res = validate_pr_title(title)
        assert not res.is_valid, f"Expected '{title}' to be invalid"


@pytest.mark.architecture
def test_pr_body_completeness_validation() -> None:
    """Ensure PR body validator enforces required sections and non-trivial content."""
    # Valid body
    valid_body = """
    ## 1. Description & Motivation (修改动机与根本原因)
    Fixes a critical race condition where sidecar processes remain alive after app crash.

    ## 2. Affected Subsystems (涉及子系统与影响面)
    - [x] `desktop` (`myrm-agent/myrm-agent-desktop/`)

    ## 3. Breaking Changes & Contract Compatibility (破坏性变更声明)
    - [x] **No breaking changes**

    ## 4. Test Plan & Verification Evidence (测试计划与验证证据)
    - **Test Command**: `./myrm test -n0 myrm-agent-harness/tests/architecture/test_pr_hygiene.py`
    - **Verification Output / Evidence**: `100% passed in 0.05s`
    """
    res = validate_pr_body(valid_body)
    assert res.is_valid, f"Expected valid body, got errors: {res.errors}"

    # Incomplete body (missing test plan)
    incomplete_body = """
    ## 1. Description & Motivation
    Some description here.

    ## 2. Affected Subsystems
    - [x] desktop

    ## 3. Breaking Changes
    None.
    """
    res = validate_pr_body(incomplete_body)
    assert not res.is_valid
    assert any("Test Plan" in err for err in res.errors)

    # Empty or sparse body
    assert not validate_pr_body("").is_valid
    assert not validate_pr_body("Too short description").is_valid

    # Body with only HTML comments
    dummy_comment_body = """
    ## 1. Description & Motivation (修改动机与根本原因)
    <!-- Fill in details -->
    ## 2. Affected Subsystems (涉及子系统与影响面)
    <!-- Subsystems -->
    ## 3. Breaking Changes & Contract Compatibility (破坏性变更声明)
    <!-- Breaking -->
    ## 4. Test Plan & Verification Evidence (测试计划与验证证据)
    <!-- Test -->
    """
    assert not validate_pr_body(dummy_comment_body).is_valid, "Pure comment PR body should be rejected"

    # Bot bypass
    assert validate_pr_body("", bypass_for_bots=True).is_valid


@pytest.mark.architecture
def test_repo_templates_exist_and_conform() -> None:
    """Ensure the repository contains compliant PR template and Issue forms on disk."""
    res = validate_issue_templates(_REPO_ROOT)
    assert res.is_valid, f"Repo templates validation failed: {res.errors}"
