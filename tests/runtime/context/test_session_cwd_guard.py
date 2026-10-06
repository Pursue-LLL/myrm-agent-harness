"""Unit tests for Session CWD Relocation Detection and Health Self-Check Guard (Item 24)."""

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.session_cwd_guard import (
    CwdHealthCheckResult,
    CwdRelocationStrategy,
    MissingSessionCwdError,
    SessionCwdHealthGuard,
    SessionCwdIssue,
)


def test_cwd_guard_existing_dir_healthy(tmp_path: Path) -> None:
    """Verifies that an existing directory passes health check without relocation."""
    result: CwdHealthCheckResult = SessionCwdHealthGuard.check_and_resolve_cwd(
        stored_cwd=str(tmp_path),
        fallback_cwd=str(tmp_path),
        session_id="sess-001",
    )
    assert result.is_healthy is True
    assert result.relocated is False
    assert result.issue is None
    assert Path(result.resolved_cwd).resolve() == tmp_path.resolve()


def test_cwd_guard_empty_or_none_cwd(tmp_path: Path) -> None:
    """Verifies that None or empty stored CWD seamlessly resolves to fallback."""
    result_none = SessionCwdHealthGuard.check_and_resolve_cwd(
        stored_cwd=None,
        fallback_cwd=str(tmp_path),
        session_id="sess-none",
    )
    assert result_none.is_healthy is True
    assert result_none.relocated is False
    assert result_none.resolved_cwd == str(tmp_path)

    result_empty = SessionCwdHealthGuard.check_and_resolve_cwd(
        stored_cwd="   ",
        fallback_cwd=str(tmp_path),
        session_id="sess-empty",
    )
    assert result_empty.is_healthy is True
    assert result_empty.relocated is False
    assert result_empty.resolved_cwd == str(tmp_path)


def test_cwd_guard_missing_dir_auto_fallback(tmp_path: Path) -> None:
    """Verifies missing directory triggers relocation to fallback directory under AUTO_FALLBACK."""
    non_existent = tmp_path / "deleted_workspace_dir"
    fallback = tmp_path / "fallback_dir"
    fallback.mkdir()

    result = SessionCwdHealthGuard.check_and_resolve_cwd(
        stored_cwd=str(non_existent),
        fallback_cwd=str(fallback),
        session_id="sess-auto",
        strategy=CwdRelocationStrategy.AUTO_FALLBACK,
    )
    assert result.is_healthy is True
    assert result.relocated is True
    assert result.resolved_cwd == str(fallback)
    assert result.strategy_used == CwdRelocationStrategy.AUTO_FALLBACK
    assert result.issue is not None
    assert result.issue.session_id == "sess-auto"
    assert "Working directory from session" in result.issue.prompt_message
    assert str(fallback) in result.issue.prompt_message


def test_cwd_guard_missing_dir_specified_path(tmp_path: Path) -> None:
    """Verifies SPECIFIED_PATH relocates to user-specified target or raises on invalid input."""
    non_existent = tmp_path / "ghost_dir"
    new_target = tmp_path / "relocated_target"
    new_target.mkdir()

    result = SessionCwdHealthGuard.check_and_resolve_cwd(
        stored_cwd=str(non_existent),
        fallback_cwd=str(tmp_path),
        session_id="sess-spec",
        strategy=CwdRelocationStrategy.SPECIFIED_PATH,
        user_specified_path=str(new_target),
    )
    assert result.is_healthy is True
    assert result.relocated is True
    assert Path(result.resolved_cwd).resolve() == new_target.resolve()
    assert result.strategy_used == CwdRelocationStrategy.SPECIFIED_PATH

    # Missing user_specified_path raises ValueError
    with pytest.raises(ValueError, match="user_specified_path must be provided"):
        SessionCwdHealthGuard.check_and_resolve_cwd(
            stored_cwd=str(non_existent),
            strategy=CwdRelocationStrategy.SPECIFIED_PATH,
            user_specified_path=None,
        )

    # Invalid user_specified_path raises NotADirectoryError
    with pytest.raises(NotADirectoryError, match="Specified relocation path is invalid"):
        SessionCwdHealthGuard.check_and_resolve_cwd(
            stored_cwd=str(non_existent),
            strategy=CwdRelocationStrategy.SPECIFIED_PATH,
            user_specified_path=str(tmp_path / "non_existent_target"),
        )


def test_cwd_guard_missing_dir_abort_raises(tmp_path: Path) -> None:
    """Verifies ABORT strategy fails closed and raises structured MissingSessionCwdError."""
    non_existent = tmp_path / "vanished_folder"
    session_file = "/path/to/my_session.json"

    with pytest.raises(MissingSessionCwdError) as exc_info:
        SessionCwdHealthGuard.check_and_resolve_cwd(
            stored_cwd=str(non_existent),
            fallback_cwd=str(tmp_path),
            session_id="sess-abort",
            session_file=session_file,
            strategy=CwdRelocationStrategy.ABORT,
        )

    err = exc_info.value
    assert err.issue.session_id == "sess-abort"
    assert err.issue.session_file == session_file
    assert "Stored session working directory does not exist" in str(err)
    assert str(non_existent) in str(err)


def test_cwd_guard_missing_dir_interactive_prompt(tmp_path: Path) -> None:
    """Verifies INTERACTIVE_PROMPT returns unhealthy with diagnostics for external prompt."""
    non_existent = tmp_path / "missing_folder"

    result = SessionCwdHealthGuard.check_and_resolve_cwd(
        stored_cwd=str(non_existent),
        fallback_cwd=str(tmp_path),
        session_id="sess-prompt",
        session_file="/workspace/.session.json",
        strategy=CwdRelocationStrategy.INTERACTIVE_PROMPT,
    )
    assert result.is_healthy is False
    assert result.relocated is False
    assert result.strategy_used == CwdRelocationStrategy.INTERACTIVE_PROMPT
    assert result.issue is not None
    assert "(from .session.json)" in result.issue.prompt_message


def test_cwd_guard_format_prompt_formatting() -> None:
    """Verifies format_prompt helper produces clean readable text."""
    issue = SessionCwdIssue(
        session_id="s1",
        stored_cwd="/old/project/path",
        fallback_cwd="/new/current/path",
        session_file="/var/log/session_file.json",
    )
    prompt = SessionCwdHealthGuard.format_prompt(issue)
    assert "Working directory from session (from session_file.json) does not exist:" in prompt
    assert "/old/project/path" in prompt
    assert "Continue in current directory?" in prompt
    assert "/new/current/path" in prompt
