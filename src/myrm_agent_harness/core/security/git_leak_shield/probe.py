"""Pre-commit and pre-push secret leak detection probe.

[INPUT]
- Unified git diff or file content text

[OUTPUT]
- PreCommitSecretProbe: Deep regex scanning probe for Git staging and commit interception
- assert_commit_safe, scan_diff, scan_content

[POS]
Harness core security probe. Intercepts `git commit` and `git push` commands,
scanning staged diffs to prevent accidental credential leakage to public repositories.
"""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.core.security.git_leak_shield.patterns import (
    SECRET_PATTERNS,
    mask_secret_value,
)
from myrm_agent_harness.core.security.git_leak_shield.types import (
    GitCommitSecretBlockedError,
    GitProbeResult,
    SecretMatch,
)

logger = logging.getLogger(__name__)

_GIT_COMMIT_PUSH_REGEX = re.compile(
    r"""\bgit\s+(?:commit|push)\b""",
    re.IGNORECASE,
)


class PreCommitSecretProbe:
    """Detects credential leaks in git diffs and code before commits are committed."""

    @classmethod
    def is_git_commit_or_push(cls, command: str) -> bool:
        """Check whether a command string involves git commit or git push."""
        return bool(_GIT_COMMIT_PUSH_REGEX.search(command))

    @classmethod
    def scan_diff(cls, diff_content: str, file_path: str = "git_diff") -> GitProbeResult:
        """Scan added lines in a unified git diff for credential patterns."""
        findings: list[SecretMatch] = []
        lines = diff_content.splitlines()
        added_lines_count = 0

        for line_idx, line in enumerate(lines, start=1):
            # Only examine newly added lines in the diff
            if not line.startswith("+") or line.startswith("+++"):
                continue

            added_lines_count += 1
            code_fragment = line[1:].strip()
            if not code_fragment or code_fragment.startswith(("//", "/*", "*", "#")):
                continue

            for secret_type, env_var, pattern in SECRET_PATTERNS:
                match = pattern.search(code_fragment)
                if match:
                    raw_val = match.group(0)
                    findings.append(
                        SecretMatch(
                            secret_type=secret_type,
                            pattern_name=secret_type,
                            line_number=line_idx,
                            raw_snippet=raw_val,
                            masked_snippet=mask_secret_value(raw_val),
                            suggested_env_var=env_var,
                            file_path=file_path,
                        )
                    )

        has_leak = len(findings) > 0
        summary = (
            f"Pre-commit scan passed: {added_lines_count} lines scanned, 0 secrets detected"
            if not has_leak
            else f"Pre-commit leak detected: {len(findings)} credential(s) found in {added_lines_count} lines"
        )
        return GitProbeResult(
            has_leak=has_leak,
            findings=findings,
            scanned_lines_count=added_lines_count,
            summary=summary,
        )

    @classmethod
    def scan_content(cls, content: str, file_path: str = "code_file") -> GitProbeResult:
        """Scan raw file content line by line for credentials."""
        findings: list[SecretMatch] = []
        lines = content.splitlines()

        for line_idx, line in enumerate(lines, start=1):
            code_fragment = line.strip()
            if not code_fragment or code_fragment.startswith(("//", "/*", "*", "#")):
                continue

            for secret_type, env_var, pattern in SECRET_PATTERNS:
                match = pattern.search(code_fragment)
                if match:
                    raw_val = match.group(0)
                    findings.append(
                        SecretMatch(
                            secret_type=secret_type,
                            pattern_name=secret_type,
                            line_number=line_idx,
                            raw_snippet=raw_val,
                            masked_snippet=mask_secret_value(raw_val),
                            suggested_env_var=env_var,
                            file_path=file_path,
                        )
                    )

        has_leak = len(findings) > 0
        summary = (
            f"Content scan passed: {len(lines)} lines scanned, 0 secrets detected"
            if not has_leak
            else f"Content leak detected: {len(findings)} credential(s) found"
        )
        return GitProbeResult(
            has_leak=has_leak,
            findings=findings,
            scanned_lines_count=len(lines),
            summary=summary,
        )

    @classmethod
    def assert_commit_safe(cls, diff_content: str, file_path: str = "git_diff") -> None:
        """Assert that a diff contains zero secrets, raising GitCommitSecretBlockedError on violation."""
        result = cls.scan_diff(diff_content, file_path=file_path)
        if result.has_leak:
            logger.error("Git commit blocked due to credential leak: %s", result.summary)
            raise GitCommitSecretBlockedError(result.findings)
