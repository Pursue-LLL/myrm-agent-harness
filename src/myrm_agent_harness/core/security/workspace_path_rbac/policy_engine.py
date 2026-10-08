"""Policy evaluation engine for Granular Workspace Path RBAC.

[INPUT]
- Normalized relative file paths, attempted file actions, and workspace policies.

[OUTPUT]
- Deterministic access verdicts, auto-reroute suggestions, and UI denial cards.

[POS]
- Filesystem RBAC evaluation barrier enforcing read/write path segregation.
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath

from myrm_agent_harness.core.security.workspace_path_rbac.types import (
    AccessCheckVerdict,
    FileActionType,
    PathAccessMode,
    WorkspacePolicy,
    WriteDenialCard,
    WriteDenialReason,
)


class WorkspacePathPolicyEngine:
    """Evaluates filesystem access against granular path RBAC rules."""

    @classmethod
    def evaluate(
        cls,
        policy: WorkspacePolicy,
        relative_path: str,
        action: FileActionType,
    ) -> AccessCheckVerdict:
        """Evaluate attempted action on relative path against policy rules."""
        norm_path = cls._normalize_path(relative_path)
        effective_mode = cls._resolve_effective_mode(policy, norm_path)

        # 1. Read operation
        if not action.is_mutation:
            if effective_mode in (PathAccessMode.RO, PathAccessMode.RW):
                return AccessCheckVerdict(
                    allowed=True,
                    effective_mode=effective_mode,
                )
            return AccessCheckVerdict(
                allowed=False,
                effective_mode=effective_mode,
                violation_reason=WriteDenialReason.UNAUTHORIZED_PATH.value,
            )

        # 2. Mutation operation (DIRECT_WRITE, COPY_WRITE, MKDIR, DELETE)
        if effective_mode == PathAccessMode.RW:
            return AccessCheckVerdict(
                allowed=True,
                effective_mode=effective_mode,
            )

        # Write attempted on RO or NONE path -> Hard Denial
        violation_reason = (
            WriteDenialReason.READ_ONLY_PATH.value
            if effective_mode == PathAccessMode.RO
            else WriteDenialReason.UNAUTHORIZED_PATH.value
        )
        dest_filename = PurePosixPath(norm_path).name or "file"
        suggested_path = f"{policy.allowed_deliverables_dir.strip('/')}/{dest_filename}"
        reroute_hint = (
            f"Path '{norm_path}' is protected (Mode: {effective_mode.value.upper()}). "
            f"Please write or redirect deliverables to authorized directory: '{suggested_path}'."
        )

        denial_card = WriteDenialCard(
            title="Unauthorized Filesystem Write Blocked",
            message=(
                f"Action '{action.value}' on protected path '{norm_path}' was denied. "
                f"Input sources are strictly Read-Only (RO) to prevent data corruption."
            ),
            blocked_path=norm_path,
            action=action.value,
            suggested_redirect_path=suggested_path,
        )

        return AccessCheckVerdict(
            allowed=False,
            effective_mode=effective_mode,
            violation_reason=violation_reason,
            auto_reroute_hint=reroute_hint,
            denial_card=denial_card,
        )

    @classmethod
    def _resolve_effective_mode(
        cls,
        policy: WorkspacePolicy,
        norm_path: str,
    ) -> PathAccessMode:
        """Match path against rules. Longest pattern match or first specific match."""
        # Check explicit rules
        for rule in policy.rules:
            pattern = rule.pattern.strip("/")
            if fnmatch.fnmatch(norm_path, pattern) or fnmatch.fnmatch(norm_path, f"{pattern}/*"):
                return rule.mode

        # Check deliverables directory default
        deliverables_prefix = policy.allowed_deliverables_dir.strip("/")
        if norm_path == deliverables_prefix or norm_path.startswith(f"{deliverables_prefix}/"):
            return PathAccessMode.RW

        # Default fallback for workspace: Read-Only for safety
        return PathAccessMode.RO

    @staticmethod
    def _normalize_path(path_str: str) -> str:
        """Normalize path to relative posix path without dot segments or leading slashes."""
        cleaned = path_str.replace("\\", "/").strip().lstrip("/")
        pure = PurePosixPath(cleaned)
        # Filter out '.' components
        parts = [p for p in pure.parts if p and p != "."]
        return "/".join(parts) if parts else ""
