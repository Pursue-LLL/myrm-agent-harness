"""Session CWD Relocation Detection, Auto-Prompt, and Health Self-Check Guard (Pi Harness v2 Item 24).

Implements the Pi Harness v2 session working directory health architecture:
1. Pre-Flight CWD Existence Probe:
   Before any agent turn or tool execution, verifies that the stored working directory
   (`session_cwd`) physically exists on the current host.
2. Graceful Relocation and Auto-Prompt Contract:
   Prevents catastrophic tool execution in wrong or missing directories ("The most common
   agent failure is not doing nothing, but acting too fast in the wrong directory").
   Provides structured relocation prompts for WebUI/Tauri/CLI with fallback paths.
3. Fail-Closed Diagnostics:
   When running non-interactively without fallbacks, raises structured `MissingSessionCwdError`
   with clear context rather than failing with silent os.chdir crashes.

[INPUT]
- stored_cwd: str | None
- fallback_cwd: str | None
- session_id: str
- session_file: str | None
- strategy: CwdRelocationStrategy

[OUTPUT]
- CwdRelocationStrategy
- SessionCwdIssue
- CwdHealthCheckResult
- MissingSessionCwdError
- SessionCwdHealthGuard

[POS]
Harness runtime context layer. Protects agent toolkits and bash execution sandboxes
from working directory drift across machines, branches, and folder moves.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CwdRelocationStrategy(StrEnum):
    """Resolution strategy when stored session CWD is missing."""

    ABORT = "abort"
    AUTO_FALLBACK = "auto_fallback"
    SPECIFIED_PATH = "specified_path"
    INTERACTIVE_PROMPT = "interactive_prompt"


@dataclass(slots=True, frozen=True)
class SessionCwdIssue:
    """Diagnostic descriptor when a session's recorded working directory is missing."""

    session_id: str
    stored_cwd: str
    fallback_cwd: str
    session_file: str | None = None
    prompt_message: str = ""


@dataclass(slots=True, frozen=True)
class CwdHealthCheckResult:
    """Result of working directory health verification."""

    is_healthy: bool
    resolved_cwd: str
    relocated: bool = False
    issue: SessionCwdIssue | None = None
    strategy_used: CwdRelocationStrategy | None = None


class MissingSessionCwdError(RuntimeError):
    """Raised when a stored session CWD does not exist and fail-closed is requested."""

    def __init__(self, issue: SessionCwdIssue) -> None:
        file_part = f"\nSession file: {issue.session_file}" if issue.session_file else ""
        msg = (
            f"Stored session working directory does not exist: {issue.stored_cwd}{file_part}\n"
            f"Current working directory: {issue.fallback_cwd}\n"
            f"Please relocate or confirm working directory before proceeding."
        )
        super().__init__(msg)
        self.issue = issue


class SessionCwdHealthGuard:
    """Guard and validator for session working directories across moves and migrations."""

    @staticmethod
    def format_prompt(issue: SessionCwdIssue) -> str:
        """Format human-friendly prompt asking user to confirm fallback directory."""
        file_info = f" (from {Path(issue.session_file).name})" if issue.session_file else ""
        return (
            f"Working directory from session{file_info} does not exist:\n"
            f"  {issue.stored_cwd}\n\n"
            f"Continue in current directory?\n"
            f"  {issue.fallback_cwd}"
        )

    @classmethod
    def check_and_resolve_cwd(
        cls,
        stored_cwd: str | None,
        *,
        fallback_cwd: str | None = None,
        session_id: str = "default",
        session_file: str | None = None,
        strategy: CwdRelocationStrategy = CwdRelocationStrategy.AUTO_FALLBACK,
        user_specified_path: str | None = None,
    ) -> CwdHealthCheckResult:
        """Probe stored CWD existence and apply configured relocation strategy."""
        active_fallback = fallback_cwd or os.getcwd()

        # If stored_cwd is empty or missing, resolve to fallback
        if not stored_cwd or not stored_cwd.strip():
            return CwdHealthCheckResult(
                is_healthy=True,
                resolved_cwd=active_fallback,
                relocated=False,
            )

        stored_path = Path(stored_cwd).expanduser().resolve()

        # Healthy: directory physically exists
        if stored_path.exists() and stored_path.is_dir():
            return CwdHealthCheckResult(
                is_healthy=True,
                resolved_cwd=str(stored_path),
                relocated=False,
            )

        # Missing directory detected: construct issue descriptor
        issue = SessionCwdIssue(
            session_id=session_id,
            stored_cwd=str(stored_path),
            fallback_cwd=active_fallback,
            session_file=session_file,
            prompt_message=cls.format_prompt(
                SessionCwdIssue(
                    session_id=session_id,
                    stored_cwd=str(stored_path),
                    fallback_cwd=active_fallback,
                    session_file=session_file,
                )
            ),
        )

        if strategy == CwdRelocationStrategy.ABORT:
            raise MissingSessionCwdError(issue)

        if strategy == CwdRelocationStrategy.SPECIFIED_PATH:
            if not user_specified_path:
                raise ValueError("user_specified_path must be provided when strategy is SPECIFIED_PATH")
            spec_path = Path(user_specified_path).expanduser().resolve()
            if not spec_path.exists() or not spec_path.is_dir():
                raise NotADirectoryError(f"Specified relocation path is invalid or does not exist: {user_specified_path}")
            return CwdHealthCheckResult(
                is_healthy=True,
                resolved_cwd=str(spec_path),
                relocated=True,
                issue=issue,
                strategy_used=CwdRelocationStrategy.SPECIFIED_PATH,
            )

        if strategy == CwdRelocationStrategy.INTERACTIVE_PROMPT:
            return CwdHealthCheckResult(
                is_healthy=False,
                resolved_cwd=active_fallback,
                relocated=False,
                issue=issue,
                strategy_used=CwdRelocationStrategy.INTERACTIVE_PROMPT,
            )

        # Default: AUTO_FALLBACK
        return CwdHealthCheckResult(
            is_healthy=True,
            resolved_cwd=active_fallback,
            relocated=True,
            issue=issue,
            strategy_used=CwdRelocationStrategy.AUTO_FALLBACK,
        )
