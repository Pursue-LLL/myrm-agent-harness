"""Isolated Branch and Directory Whitelist Gate for Dev Sandbox."""

from __future__ import annotations

import os

from .types import DevSandboxPolicy, FenceInspectionResult, ViolationType


class BranchAndDirectoryGate:
    """Enforces Git branch isolation and directory write restrictions for development agents."""

    def inspect_git_branch(
        self, branch_name: str, policy: DevSandboxPolicy
    ) -> FenceInspectionResult:
        """Verify whether git branch is an approved isolated development branch."""
        norm_branch = branch_name.strip()
        lowered = norm_branch.lower()

        # 1. Blocked branch check (main, master, production, etc.)
        for blocked in policy.blocked_branches:
            if lowered == blocked or lowered.startswith(f"{blocked}/"):
                return FenceInspectionResult(
                    allowed=False,
                    violation_type=ViolationType.PROD_BRANCH_PUSH_BLOCKED,
                    reason=f"Direct modification or push to production branch '{branch_name}' is strictly forbidden in dev mode",
                )

        # 2. Allowed branch prefix check (must start with approved prefix)
        allowed_prefix = any(
            lowered.startswith(prefix.lower())
            for prefix in policy.allowed_branch_prefixes
        )
        if not allowed_prefix:
            return FenceInspectionResult(
                allowed=False,
                violation_type=ViolationType.PROD_BRANCH_PUSH_BLOCKED,
                reason=f"Branch '{branch_name}' does not match allowed dev branch prefixes: {list(policy.allowed_branch_prefixes)}",
            )

        return FenceInspectionResult(
            allowed=True,
            violation_type=None,
            reason=f"Branch '{branch_name}' conforms to isolated dev branch standards",
        )

    def inspect_file_write(
        self, file_path: str, policy: DevSandboxPolicy
    ) -> FenceInspectionResult:
        """Verify whether a file write target is within allowed dev directories and not sensitive."""
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        lowered_path = norm_path.lower()

        # 1. Sensitive directory and pattern check
        for pattern in policy.blocked_sensitive_patterns:
            lowered_pat = pattern.lower().rstrip("/")
            if (
                lowered_pat in lowered_path
                or lowered_path.startswith(lowered_pat)
                or lowered_path.endswith(lowered_pat)
            ):
                return FenceInspectionResult(
                    allowed=False,
                    violation_type=ViolationType.SENSITIVE_DIR_WRITE_BLOCKED,
                    reason=f"File path '{file_path}' matches sensitive production pattern '{pattern}' and cannot be modified in dev mode",
                )

        # 2. Allowed write directories check
        in_allowed_dir = False
        for allowed_dir in policy.allowed_write_directories:
            norm_allowed = os.path.normpath(allowed_dir).replace("\\", "/").lower().rstrip("/")
            if (
                lowered_path.startswith(f"{norm_allowed}/")
                or lowered_path == norm_allowed
                or f"/{norm_allowed}/" in lowered_path
            ):
                in_allowed_dir = True
                break

        if not in_allowed_dir:
            return FenceInspectionResult(
                allowed=False,
                violation_type=ViolationType.SENSITIVE_DIR_WRITE_BLOCKED,
                reason=f"File path '{file_path}' is outside authorized dev directories {list(policy.allowed_write_directories)}",
            )

        return FenceInspectionResult(
            allowed=True,
            violation_type=None,
            reason=f"File path '{file_path}' is within authorized dev sandbox directory",
        )
