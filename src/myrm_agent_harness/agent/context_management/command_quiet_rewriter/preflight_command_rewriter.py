"""Preflight Command Rewriter that intercepts CLI commands before sandbox execution.

Automatically detects verbose CLI patterns (e.g. pytest, vitest, npm, git log, curl)
and injects quiet / silent / limit flags to eliminate terminal noise at the source.
"""

from __future__ import annotations

import re
import shlex
from typing import Sequence

from .quiet_rewriter_types import (
    QuietRewriteRule,
    RewriteResult,
    RewriteStatus,
)


class PreflightCommandRewriter:
    """Intelligent pre-execution rewriter for CLI commands to suppress redundant terminal noise."""

    DEFAULT_RULES: list[QuietRewriteRule] = [
        QuietRewriteRule(
            rule_id="pytest",
            target_tool="pytest",
            flags_to_inject=["-q", "--tb=short"],
            verbose_flags=("-v", "-vv", "-vvv", "--verbose"),
            quiet_flags=("-q", "--quiet", "--silent"),
            description="Inject -q --tb=short into pytest to eliminate 100+ passed dot lines.",
            priority=10,
        ),
        QuietRewriteRule(
            rule_id="vitest",
            target_tool="vitest",
            flags_to_inject=["--reporter=dot", "--silent"],
            verbose_flags=("-v", "--verbose"),
            quiet_flags=("--silent", "--reporter=dot"),
            description="Inject dot reporter and silent flag into vitest.",
            priority=20,
        ),
        QuietRewriteRule(
            rule_id="jest",
            target_tool="jest",
            flags_to_inject=["--silent"],
            verbose_flags=("--verbose",),
            quiet_flags=("--silent",),
            description="Inject --silent into jest test runs.",
            priority=30,
        ),
        QuietRewriteRule(
            rule_id="npm_install",
            target_tool="npm",
            flags_to_inject=["--silent"],
            verbose_flags=("--verbose", "-d", "--loglevel=verbose"),
            quiet_flags=("--silent", "-s", "--quiet"),
            description="Inject --silent into npm install/add commands.",
            priority=40,
        ),
        QuietRewriteRule(
            rule_id="pnpm",
            target_tool="pnpm",
            flags_to_inject=["--silent"],
            verbose_flags=("--verbose",),
            quiet_flags=("--silent",),
            description="Inject --silent into pnpm package manager commands.",
            priority=50,
        ),
        QuietRewriteRule(
            rule_id="yarn",
            target_tool="yarn",
            flags_to_inject=["--silent"],
            verbose_flags=("--verbose",),
            quiet_flags=("--silent",),
            description="Inject --silent into yarn commands.",
            priority=60,
        ),
        QuietRewriteRule(
            rule_id="git_log",
            target_tool="git",
            flags_to_inject=["--oneline", "-n", "20"],
            verbose_flags=("--stat", "--patch", "-p"),
            quiet_flags=("--oneline", "-n", "--max-count"),
            description="Limit unbounded git log commands to oneline and 20 commits.",
            priority=70,
        ),
        QuietRewriteRule(
            rule_id="curl",
            target_tool="curl",
            flags_to_inject=["-s", "-S"],
            verbose_flags=("-v", "--verbose"),
            quiet_flags=("-s", "--silent"),
            description="Inject silent mode into curl while preserving error output.",
            priority=80,
        ),
        QuietRewriteRule(
            rule_id="wget",
            target_tool="wget",
            flags_to_inject=["-q"],
            verbose_flags=("-v", "--verbose"),
            quiet_flags=("-q", "--quiet"),
            description="Inject -q into wget downloads.",
            priority=90,
        ),
    ]

    def __init__(
        self,
        custom_rules: Sequence[QuietRewriteRule] | None = None,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._rules = sorted(
            list(custom_rules or self.DEFAULT_RULES),
            key=lambda r: r.priority,
        )

    def rewrite(self, command: str) -> RewriteResult:
        """Inspect and rewrite a command line string if applicable."""
        clean_cmd = command.strip()
        if not clean_cmd:
            return RewriteResult(
                original_command=command,
                rewritten_command=command,
                status=RewriteStatus.UNCHANGED,
                reason="Empty command.",
            )

        if not self.enabled:
            return RewriteResult(
                original_command=command,
                rewritten_command=command,
                status=RewriteStatus.BYPASSED_DISABLED,
                reason="Rewriter disabled by configuration.",
            )

        # Check for command separators like &&, ||, ;, |
        if any(sep in clean_cmd for sep in ["&&", "||", ";", "|"]):
            return self._rewrite_compound_command(clean_cmd)

        return self._rewrite_single_segment(clean_cmd)

    def _rewrite_compound_command(self, full_cmd: str) -> RewriteResult:
        """Process compound commands by splitting by operators and rewriting segments."""
        # Split while preserving operators
        tokens = re.split(r"(\s*(?:&&|\|\||;|\|)\s*)", full_cmd)
        rewritten_parts: list[str] = []
        any_modified = False
        matched_rule_id: str | None = None
        injected: list[str] = []

        for part in tokens:
            if not part:
                continue
            stripped = part.strip()
            if stripped in ["&&", "||", ";", "|"]:
                rewritten_parts.append(part)
                continue

            res = self._rewrite_single_segment(stripped)
            if res.was_modified:
                any_modified = True
                rewritten_parts.append(res.rewritten_command)
                if not matched_rule_id:
                    matched_rule_id = res.matched_rule
                injected.extend(res.injected_flags)
            else:
                rewritten_parts.append(stripped)

        final_command = "".join(rewritten_parts)
        if any_modified:
            return RewriteResult(
                original_command=full_cmd,
                rewritten_command=final_command,
                status=RewriteStatus.REWRITTEN,
                matched_rule=matched_rule_id,
                injected_flags=injected,
                reason="One or more segments in compound command were quieted.",
            )
        return RewriteResult(
            original_command=full_cmd,
            rewritten_command=full_cmd,
            status=RewriteStatus.UNCHANGED,
            reason="No compound segments qualified for quiet rewrite.",
        )

    def _rewrite_single_segment(self, segment: str) -> RewriteResult:
        """Analyze and rewrite a single isolated command token stream."""
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()

        if not tokens:
            return RewriteResult(
                original_command=segment,
                rewritten_command=segment,
                status=RewriteStatus.UNCHANGED,
            )

        cmd_name = tokens[0]
        # Resolve python -m pytest or npx vitest prefix
        rule = self._find_matching_rule(cmd_name, tokens)
        if not rule:
            return RewriteResult(
                original_command=segment,
                rewritten_command=segment,
                status=RewriteStatus.UNCHANGED,
                reason=f"No matching quiet rule for '{cmd_name}'.",
            )

        # 1. Check if user or LLM explicitly requested verbose output
        for arg in tokens[1:]:
            if arg in rule.verbose_flags or any(arg.startswith(vf) for vf in rule.verbose_flags if vf.startswith("--")):
                return RewriteResult(
                    original_command=segment,
                    rewritten_command=segment,
                    status=RewriteStatus.BYPASSED_EXPLICIT_VERBOSE,
                    matched_rule=rule.rule_id,
                    reason=f"Explicit verbose flag '{arg}' detected; preserving caller intent.",
                )

        # 2. Check if quiet flags are already present
        if any(arg in rule.quiet_flags for arg in tokens[1:]):
            return RewriteResult(
                original_command=segment,
                rewritten_command=segment,
                status=RewriteStatus.UNCHANGED,
                matched_rule=rule.rule_id,
                reason="Command already includes quiet or limit flags.",
            )

        # 3. Special handling for git log: only apply when git subcommand is log
        if rule.rule_id == "git_log":
            if len(tokens) < 2 or tokens[1] != "log":
                return RewriteResult(
                    original_command=segment,
                    rewritten_command=segment,
                    status=RewriteStatus.UNCHANGED,
                    matched_rule=rule.rule_id,
                    reason="Git command is not 'log'.",
                )
            # check if any limit -<number> is present (e.g. -1, -5, -20)
            if any(re.match(r"^-\d+$", arg) for arg in tokens[2:]):
                return RewriteResult(
                    original_command=segment,
                    rewritten_command=segment,
                    status=RewriteStatus.UNCHANGED,
                    matched_rule=rule.rule_id,
                    reason="Git log already bounded by commit count flag.",
                )

        # 4. Special handling for npm: only apply on install / i / test
        if rule.rule_id == "npm_install":
            if len(tokens) < 2 or tokens[1] not in ("install", "i", "add", "ci"):
                return RewriteResult(
                    original_command=segment,
                    rewritten_command=segment,
                    status=RewriteStatus.UNCHANGED,
                    matched_rule=rule.rule_id,
                    reason="Npm command is not an installation subcommand.",
                )

        # 5. Inject flags
        rewritten = self._inject_flags(segment, tokens, rule)
        return RewriteResult(
            original_command=segment,
            rewritten_command=rewritten,
            status=RewriteStatus.REWRITTEN,
            matched_rule=rule.rule_id,
            injected_flags=rule.flags_to_inject,
            reason=rule.description,
        )

    def _find_matching_rule(self, cmd_name: str, tokens: list[str]) -> QuietRewriteRule | None:
        """Find the most appropriate QuietRewriteRule for the given command tokens."""
        # Direct match on first token
        for rule in self._rules:
            if cmd_name == rule.target_tool or cmd_name.endswith(f"/{rule.target_tool}"):
                return rule

        # Subcommand matching, e.g. python -m pytest or npx vitest
        if cmd_name in ("python", "python3", "python3.13") and len(tokens) >= 3 and tokens[1] == "-m":
            module_name = tokens[2]
            for rule in self._rules:
                if module_name == rule.target_tool:
                    return rule

        if cmd_name in ("npx", "bunx") and len(tokens) >= 2:
            subtool = tokens[1]
            for rule in self._rules:
                if subtool == rule.target_tool:
                    return rule

        return None

    def _inject_flags(self, original_segment: str, tokens: list[str], rule: QuietRewriteRule) -> str:
        """Intelligently append or insert flags into the command line."""
        # For git log, insert flags right after 'git log'
        if rule.rule_id == "git_log":
            return original_segment.replace("git log", f"git log {' '.join(rule.flags_to_inject)}", 1)

        # For general commands, append flags cleanly
        flags_str = " ".join(rule.flags_to_inject)
        return f"{original_segment.rstrip()} {flags_str}"
