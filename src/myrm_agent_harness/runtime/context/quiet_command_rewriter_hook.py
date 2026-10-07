"""Quiet command rewriter hook.

Intercepts high-volume terminal commands (pytest, npm test, cargo test, git status)
and injects quiet/concise flags before execution, preventing thousands of verbose
lines from flooding the active conversation window while respecting explicit user verbosity.
"""

from __future__ import annotations

import re

from .quiet_command_spill_types import CommandCategory, CommandRewriteResult


class QuietCommandRewriterHook:
    """Pre-execution hook that transparently adds quiet flags to noisy developer commands."""

    def __init__(self, enabled: bool = True) -> None:
        self._enabled = enabled

    def rewrite_command(self, command: str) -> CommandRewriteResult:
        """Evaluates and rewrites command string to inject quiet/compact flags."""
        cmd_clean = command.strip()
        if not self._enabled or not cmd_clean:
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=command,
                is_rewritten=False,
                category=None,
                injected_flag="",
                reason="hook_disabled_or_empty_command",
            )

        # Respect explicit verbose / debug intents
        if self._has_explicit_verbose_intent(cmd_clean):
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=command,
                is_rewritten=False,
                category=None,
                injected_flag="",
                reason="explicit_verbose_intent_detected",
            )

        # 1. Pytest
        if re.search(r"\bpytest\b", cmd_clean) and not re.search(r"\s+(-q|--quiet|-qq)\b", cmd_clean):
            rewritten = f"{cmd_clean} -q"
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=rewritten,
                is_rewritten=True,
                category=CommandCategory.TEST_RUNNER,
                injected_flag="-q",
                reason="injected_pytest_quiet_flag",
            )

        # 2. NPM test
        if re.search(r"\bnpm\s+(test|t)\b", cmd_clean) and not re.search(r"\s+(--silent|-s|--quiet)\b", cmd_clean):
            rewritten = f"{cmd_clean} --silent"
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=rewritten,
                is_rewritten=True,
                category=CommandCategory.TEST_RUNNER,
                injected_flag="--silent",
                reason="injected_npm_test_silent_flag",
            )

        # 3. Git status
        if re.search(r"\bgit\s+status\b", cmd_clean) and not re.search(r"\s+(-s|--short)\b", cmd_clean):
            rewritten = f"{cmd_clean} -s"
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=rewritten,
                is_rewritten=True,
                category=CommandCategory.VCS,
                injected_flag="-s",
                reason="injected_git_status_short_flag",
            )

        # 4. Cargo test
        if re.search(r"\bcargo\s+test\b", cmd_clean) and not re.search(r"\s+(-q|--quiet)\b", cmd_clean):
            rewritten = f"{cmd_clean} -q"
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=rewritten,
                is_rewritten=True,
                category=CommandCategory.TEST_RUNNER,
                injected_flag="-q",
                reason="injected_cargo_test_quiet_flag",
            )

        # 5. Pip install
        if re.search(r"\bpip\s+install\b", cmd_clean) and not re.search(r"\s+(-q|--quiet|-qq)\b", cmd_clean):
            rewritten = f"{cmd_clean} -q"
            return CommandRewriteResult(
                original_command=command,
                rewritten_command=rewritten,
                is_rewritten=True,
                category=CommandCategory.PACKAGE_MANAGER,
                injected_flag="-q",
                reason="injected_pip_install_quiet_flag",
            )

        return CommandRewriteResult(
            original_command=command,
            rewritten_command=command,
            is_rewritten=False,
            category=None,
            injected_flag="",
            reason="command_not_matching_noisy_patterns",
        )

    def _has_explicit_verbose_intent(self, cmd: str) -> bool:
        """Checks if the user explicitly requested verbose/debug output."""
        return bool(re.search(r"\s+(-v|--verbose|-vv|--debug|-x)\b", cmd))
