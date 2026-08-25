"""Privacy Fail-Closed Ladder — three-level hierarchy for sandboxed workspace persistence.

Enforces a fail-closed privacy verification ladder (Workspace-level -> Session-level -> File-level)
prior to workspace snapshotting, file mutations, or cloud persistence commits.

[INPUT]
- core.security.types::SensitivityLevel, PrivacyPolicy
- core.security.guards.privacy_tracker::get_privacy_policy, get_privacy_tracker
- core.security.path_security::is_within_boundary, is_dangerous_path, is_blocked_device_path
- core.security.detection.pii_classifier::classify_content

[OUTPUT]
- PrivacyLadderLevel: Enum (WORKSPACE, SESSION, FILE)
- PrivacyScope: Immutable dataclass defining boundaries and allowed sensitivity ceilings
- PrivacyLadderVerdict: Immutable verification result
- PrivacyLadderViolationType: Enum of specific ladder security violations
- PrivacyFailClosedLadder: Pure validator for multi-level privacy constraint verification
- PrivacyFailClosedViolationError: Exception raised on fail-closed breach

[POS]
Layer 2.5 / Core Security Subsystem. Single Source of Truth for privacy fail-closed ladder
governing per-turn sandboxed persistence and file writes.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Final

from myrm_agent_harness.core.security.detection.pii_classifier import classify_content
from myrm_agent_harness.core.security.guards.privacy_tracker import (
    get_privacy_policy,
    get_privacy_tracker,
)
from myrm_agent_harness.core.security.path_security import (
    is_blocked_device_path,
    is_dangerous_path,
    is_within_boundary,
)
from myrm_agent_harness.core.security.types import PrivacyPolicy, SensitivityLevel

logger = logging.getLogger(__name__)


class PrivacyLadderLevel(StrEnum):
    """Hierarchy levels of the privacy ladder."""

    WORKSPACE = "workspace"
    SESSION = "session"
    FILE = "file"


class PrivacyLadderViolationType(StrEnum):
    """Specific violation types encountered on the privacy ladder."""

    WORKSPACE_BOUNDARY_ESCAPED = "workspace_boundary_escaped"
    DANGEROUS_SYSTEM_PATH = "dangerous_system_path"
    BLOCKED_DEVICE = "blocked_device"
    SESSION_SENSITIVITY_EXCEEDED = "session_sensitivity_exceeded"
    UNENCRYPTED_S3_CONFIDENTIAL = "unencrypted_s3_confidential"
    RESTRICTED_FILE_MODIFICATION = "restricted_file_modification"


@dataclass(frozen=True, slots=True)
class PrivacyScope:
    """Immutable privacy boundary configuration for sandboxed execution and persistence.

    Attributes:
        workspace_root: Physical root path of the allowed workspace volume.
        allowed_extra_roots: Additional allowed directories for persistence/mounts.
        max_allowed_sensitivity: Maximum permitted sensitivity (S1, S2, or S3).
        allow_s3_persistence: Whether S3-level confidential data is permitted to persist unencrypted.
        restricted_patterns: Glob or substring patterns of files restricted from persistence.
    """

    workspace_root: str
    allowed_extra_roots: tuple[str, ...] = ()
    max_allowed_sensitivity: SensitivityLevel = SensitivityLevel.S3
    allow_s3_persistence: bool = False
    restricted_patterns: tuple[str, ...] = (
        ".git/config",
        "*.pem",
        "*.key",
        "id_rsa",
        "id_ed25519",
    )


@dataclass(frozen=True, slots=True)
class PrivacyLadderVerdict:
    """Immutable outcome of evaluating a privacy ladder check."""

    is_allowed: bool
    level: PrivacyLadderLevel | None = None
    violation_type: PrivacyLadderViolationType | None = None
    reason: str = ""
    detected_sensitivity: SensitivityLevel = SensitivityLevel.S1
    matched_patterns: tuple[str, ...] = ()


class PrivacyFailClosedViolationError(PermissionError):
    """Raised when a persistence or file write violates the privacy fail-closed ladder."""

    def __init__(self, verdict: PrivacyLadderVerdict, target_path: str = "") -> None:
        self.verdict = verdict
        self.target_path = target_path
        super().__init__(
            f"[PrivacyFailClosedLadder] Blocked at level '{verdict.level}': {verdict.reason} (target: {target_path})"
        )


def _normalize_path(path_str: str) -> str:
    """Expand and resolve path with OS case-normalization."""
    expanded = os.path.expanduser(path_str.strip())
    resolved = os.path.realpath(expanded)
    if sys.platform in ("darwin", "win32"):
        return os.path.normcase(resolved)
    return resolved


class PrivacyFailClosedLadder:
    """Pure-validator engine for three-level privacy fail-closed verification."""

    @staticmethod
    def evaluate(
        target_path: str,
        content: str | bytes | None = None,
        *,
        scope: PrivacyScope | None = None,
        session_turn_level: SensitivityLevel | None = None,
        privacy_policy: PrivacyPolicy | None = None,
    ) -> PrivacyLadderVerdict:
        """Evaluate the privacy fail-closed ladder across Workspace -> Session -> File.

        Evaluation order (fail-closed short-circuit):
        1. Level 3 (Workspace-level): Target path must be safely enclosed in workspace/extra boundaries,
           cannot be a dangerous host system directory, and cannot be a blocked hardware device.
        2. Level 2 (Session-level): Current session sensitivity must not exceed scope ceiling.
        3. Level 1 (File-level): Inspect content for S3/confidential data and verify restricted files.

        Returns:
            PrivacyLadderVerdict containing evaluation details.
        """
        if not target_path or not isinstance(target_path, str):
            return PrivacyLadderVerdict(
                is_allowed=False,
                level=PrivacyLadderLevel.WORKSPACE,
                violation_type=PrivacyLadderViolationType.WORKSPACE_BOUNDARY_ESCAPED,
                reason="Target path is empty or invalid",
            )

        # ---------------------------------------------------------------------
        # Level 3: Workspace-level Boundary Verification
        # ---------------------------------------------------------------------
        if is_blocked_device_path(target_path):
            return PrivacyLadderVerdict(
                is_allowed=False,
                level=PrivacyLadderLevel.WORKSPACE,
                violation_type=PrivacyLadderViolationType.BLOCKED_DEVICE,
                reason=f"Target path '{target_path}' is a blocked system device",
            )

        if is_dangerous_path(target_path):
            return PrivacyLadderVerdict(
                is_allowed=False,
                level=PrivacyLadderLevel.WORKSPACE,
                violation_type=PrivacyLadderViolationType.DANGEROUS_SYSTEM_PATH,
                reason=f"Target path '{target_path}' points to a protected host system path",
            )

        if scope is not None and scope.workspace_root:
            normalized_target = _normalize_path(target_path)
            normalized_root = _normalize_path(scope.workspace_root)

            in_root = is_within_boundary(normalized_target, normalized_root)
            in_extra = any(
                is_within_boundary(normalized_target, _normalize_path(extra))
                for extra in scope.allowed_extra_roots
                if extra
            )

            if not (in_root or in_extra):
                return PrivacyLadderVerdict(
                    is_allowed=False,
                    level=PrivacyLadderLevel.WORKSPACE,
                    violation_type=PrivacyLadderViolationType.WORKSPACE_BOUNDARY_ESCAPED,
                    reason=(
                        f"Target path '{target_path}' escapes authorized workspace root '{scope.workspace_root}'"
                    ),
                )

        # ---------------------------------------------------------------------
        # Level 2: Session-level Sensitivity Ceiling
        # ---------------------------------------------------------------------
        active_turn_level = session_turn_level
        if active_turn_level is None:
            active_turn_level = get_privacy_tracker().current_turn_level

        effective_scope = scope or PrivacyScope(workspace_root="")
        _level_order: Final[dict[SensitivityLevel, int]] = {
            SensitivityLevel.S1: 1,
            SensitivityLevel.S2: 2,
            SensitivityLevel.S3: 3,
        }

        if _level_order.get(active_turn_level, 1) > _level_order.get(effective_scope.max_allowed_sensitivity, 3):
            return PrivacyLadderVerdict(
                is_allowed=False,
                level=PrivacyLadderLevel.SESSION,
                violation_type=PrivacyLadderViolationType.SESSION_SENSITIVITY_EXCEEDED,
                reason=(
                    f"Current session sensitivity '{active_turn_level.value}' exceeds "
                    f"maximum allowed privacy ceiling '{effective_scope.max_allowed_sensitivity.value}'"
                ),
                detected_sensitivity=active_turn_level,
            )

        # ---------------------------------------------------------------------
        # Level 1: File-level Content Inspection & Restricted Patterns
        # ---------------------------------------------------------------------
        path_obj = Path(target_path)
        for pattern in effective_scope.restricted_patterns:
            if path_obj.match(pattern) or pattern in target_path:
                return PrivacyLadderVerdict(
                    is_allowed=False,
                    level=PrivacyLadderLevel.FILE,
                    violation_type=PrivacyLadderViolationType.RESTRICTED_FILE_MODIFICATION,
                    reason=f"Target path '{target_path}' matches restricted privacy pattern '{pattern}'",
                )

        if content is not None:
            text_to_scan = content if isinstance(content, str) else content.decode("utf-8", errors="ignore")
            if text_to_scan:
                policy = privacy_policy or get_privacy_policy()
                # For fail-closed ladder file content inspection, ensure enabled policy is used
                if not policy.enabled:
                    policy = PrivacyPolicy(enabled=True)
                classification = classify_content(text_to_scan, policy)

                if classification.level == SensitivityLevel.S3 and not effective_scope.allow_s3_persistence:
                    return PrivacyLadderVerdict(
                        is_allowed=False,
                        level=PrivacyLadderLevel.FILE,
                        violation_type=PrivacyLadderViolationType.UNENCRYPTED_S3_CONFIDENTIAL,
                        reason=(
                            "Content contains S3 confidential personal/credential data prohibited "
                            "from unencrypted workspace persistence"
                        ),
                        detected_sensitivity=SensitivityLevel.S3,
                        matched_patterns=tuple(classification.patterns),
                    )

        return PrivacyLadderVerdict(
            is_allowed=True,
            detected_sensitivity=active_turn_level,
        )

    @classmethod
    def assert_valid(
        cls,
        target_path: str,
        content: str | bytes | None = None,
        *,
        scope: PrivacyScope | None = None,
        session_turn_level: SensitivityLevel | None = None,
        privacy_policy: PrivacyPolicy | None = None,
    ) -> None:
        """Evaluate ladder and immediately raise PrivacyFailClosedViolationError if not allowed."""
        verdict = cls.evaluate(
            target_path=target_path,
            content=content,
            scope=scope,
            session_turn_level=session_turn_level,
            privacy_policy=privacy_policy,
        )
        if not verdict.is_allowed:
            logger.error(
                "[PrivacyLadder] Fail-closed blocked on %s (level=%s, type=%s): %s",
                target_path,
                verdict.level,
                verdict.violation_type,
                verdict.reason,
            )
            raise PrivacyFailClosedViolationError(verdict, target_path=target_path)
