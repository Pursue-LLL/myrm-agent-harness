"""
[POS] src/myrm_agent_harness/core/security/host_execution_guard/path_shield_overlay.py
[INPUT] pathlib, os, typing
[OUTPUT] PathShieldOverlay

Local host sensitive directory protection and virtual scratch overlay redirector.
Mechanically locks down root and system directories to prevent destroying home servers.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import os
from pathlib import Path

from .types import PathAccessMode, PathInspectionResult, PathProtectionAction


class PathShieldOverlay:
    """Enforces mechanical read-only protections on critical system directories and handles virtual overlays."""

    DEFAULT_PROTECTED_PREFIXES: tuple[str, ...] = (
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/var",
        "/boot",
        "/dev",
        "/proc",
        "/sys",
        "/System",
        "/Library",
        "/private/etc",
        "/private/var",
        "C:\\Windows",
        "C:\\Program Files",
        "C:\\Program Files (x86)",
    )

    DEFAULT_PROTECTED_USER_DIRS: tuple[str, ...] = (
        ".ssh",
        ".gnupg",
        ".aws",
        ".kube",
        ".config/gcloud",
        ".docker",
    )

    def __init__(
        self,
        workspace_root: str | None = None,
        scratch_overlay_dir: str | None = None,
        custom_protected_paths: tuple[str, ...] | None = None,
    ) -> None:
        self._workspace_root = os.path.abspath(workspace_root) if workspace_root else None
        self._scratch_overlay_dir = (
            os.path.abspath(scratch_overlay_dir) if scratch_overlay_dir else None
        )
        self._custom_protected = custom_protected_paths or ()
        self._user_home = os.path.expanduser("~")

    @property
    def workspace_root(self) -> str | None:
        """Active workspace root directory."""
        return self._workspace_root

    @property
    def scratch_overlay_dir(self) -> str | None:
        """Active scratch overlay staging directory."""
        return self._scratch_overlay_dir

    def inspect_path(
        self,
        target_path: str,
        mode: PathAccessMode = PathAccessMode.WRITE,
    ) -> PathInspectionResult:
        """Inspect target path access against system protection rules and determine redirection."""
        expanded_target = os.path.abspath(os.path.expanduser(target_path))

        # 1. READ operations outside strictly private credentials are generally allowed
        if mode == PathAccessMode.READ:
            if self._is_private_credential_path(expanded_target):
                return PathInspectionResult(
                    original_path=target_path,
                    is_protected=True,
                    action=PathProtectionAction.BLOCK,
                    effective_path=expanded_target,
                    explanation=f"Read access to confidential user credential store '{target_path}' is blocked.",
                )
            return PathInspectionResult(
                original_path=target_path,
                is_protected=False,
                action=PathProtectionAction.ALLOW,
                effective_path=expanded_target,
                explanation="Read access permitted under mechanical host guardrail.",
            )

        # 2. WRITE/DELETE/EXECUTE inside active workspace root is allowed
        if self._workspace_root and self._is_subpath(expanded_target, self._workspace_root):
            return PathInspectionResult(
                original_path=target_path,
                is_protected=False,
                action=PathProtectionAction.ALLOW,
                effective_path=expanded_target,
                explanation=f"Target path is within authorized workspace root '{self._workspace_root}'.",
            )

        # 3. Check protected system prefixes and credentials
        is_sys_protected = self._is_system_protected_path(expanded_target)
        is_cred_protected = self._is_private_credential_path(expanded_target)

        if is_sys_protected or is_cred_protected:
            # If scratch overlay is enabled and not a sensitive credential, redirect to scratch overlay
            if self._scratch_overlay_dir and not is_cred_protected:
                rel_suffix = expanded_target.lstrip(os.path.sep).replace(":", "")
                effective_redirect = os.path.join(self._scratch_overlay_dir, rel_suffix)
                return PathInspectionResult(
                    original_path=target_path,
                    is_protected=True,
                    action=PathProtectionAction.VIRTUAL_OVERLAY,
                    effective_path=effective_redirect,
                    explanation=(
                        f"System path '{target_path}' is protected. Write redirected to "
                        f"virtual scratch overlay at '{effective_redirect}'."
                    ),
                )
            # Otherwise, mechanically block write to prevent destroying the host machine
            return PathInspectionResult(
                original_path=target_path,
                is_protected=True,
                action=PathProtectionAction.BLOCK,
                effective_path=expanded_target,
                explanation=(
                    f"Modification to protected host path '{target_path}' is strictly blocked "
                    "to prevent host system corruption."
                ),
            )

        # 4. If outside workspace and no explicit rule matched
        if self._workspace_root and not self._is_subpath(expanded_target, self._workspace_root):
            if self._scratch_overlay_dir:
                rel_suffix = expanded_target.lstrip(os.path.sep).replace(":", "")
                effective_redirect = os.path.join(self._scratch_overlay_dir, rel_suffix)
                return PathInspectionResult(
                    original_path=target_path,
                    is_protected=True,
                    action=PathProtectionAction.VIRTUAL_OVERLAY,
                    effective_path=effective_redirect,
                    explanation=(
                        f"Path '{target_path}' is outside workspace. Redirected to scratch overlay "
                        f"at '{effective_redirect}'."
                    ),
                )
            return PathInspectionResult(
                original_path=target_path,
                is_protected=True,
                action=PathProtectionAction.BLOCK,
                effective_path=expanded_target,
                explanation=f"Write outside authorized workspace root '{self._workspace_root}' is blocked.",
            )

        return PathInspectionResult(
            original_path=target_path,
            is_protected=False,
            action=PathProtectionAction.ALLOW,
            effective_path=expanded_target,
            explanation="Path access permitted.",
        )

    def _is_system_protected_path(self, abs_path: str) -> bool:
        norm = os.path.normpath(abs_path)
        # Root directory itself
        if norm in ("/", "\\") or norm == os.path.splitdrive(norm)[0] + os.path.sep:
            return True

        for prefix in self.DEFAULT_PROTECTED_PREFIXES:
            if self._is_subpath(norm, prefix) or norm.lower() == prefix.lower():
                return True

        return any(
            self._is_subpath(norm, custom) or norm == custom
            for custom in self._custom_protected
        )

    def _is_private_credential_path(self, abs_path: str) -> bool:
        norm = os.path.normpath(abs_path)
        for user_rel in self.DEFAULT_PROTECTED_USER_DIRS:
            target_cred = os.path.normpath(os.path.join(self._user_home, user_rel))
            if self._is_subpath(norm, target_cred) or norm == target_cred:
                return True
        return False

    @staticmethod
    def _is_subpath(child: str, parent: str) -> bool:
        try:
            Path(child).resolve().relative_to(Path(parent).resolve())
            return True
        except (ValueError, RuntimeError):
            return False
