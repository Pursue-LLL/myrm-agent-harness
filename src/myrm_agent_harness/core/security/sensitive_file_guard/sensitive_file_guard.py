"""Sensitive Vault and Credential File Overwrite Deny Guard Engine."""

from __future__ import annotations

import logging
import threading
import uuid

from .deny_rules import SensitivePathDenyRules
from .types import (
    PermissionDeniedSensitiveFileError,
    SensitiveFileDecision,
    SensitiveFileInspection,
    SensitiveFileViolationAlert,
)
from .unlock_manager import FileUnlockManager

logger = logging.getLogger(__name__)


class SensitiveVaultAndCredentialFileOverwriteDenyGuard:
    """Hard security guard preventing unauthorized overwrite, deletion, or truncation of sensitive files."""

    def __init__(
        self,
        rules: SensitivePathDenyRules | None = None,
        unlock_manager: FileUnlockManager | None = None,
    ) -> None:
        self.rules = rules or SensitivePathDenyRules()
        self.unlock_manager = unlock_manager or FileUnlockManager()
        self._lock = threading.Lock()
        self._alerts: list[SensitiveFileViolationAlert] = []

    def inspect_file_operation(
        self, inspection: SensitiveFileInspection
    ) -> SensitiveFileDecision:
        """Inspect proposed file mutation (write, overwrite, append, replace, delete)."""
        matched_rule = self.rules.match_path(inspection.target_path)

        # 1. Non-sensitive target: allowed
        if matched_rule is None:
            return SensitiveFileDecision(
                allowed=True,
                matched_rule=None,
                reason="Target path is not a protected sensitive credential or vault file",
                is_unlocked=False,
            )

        # 2. Check if file is unlocked via explicit user token grant
        if self.unlock_manager.validate_grant(
            inspection.target_path, inspection.unlock_token
        ):
            logger.info(
                "Sensitive file write permitted via valid unlock token: %s (Tool: %s)",
                inspection.target_path,
                inspection.tool_name,
            )
            return SensitiveFileDecision(
                allowed=True,
                matched_rule=matched_rule,
                reason=f"Target sensitive file '{inspection.target_path}' unlocked by active user grant",
                is_unlocked=True,
            )

        # 3. Blocked: Raise audit alert and deny
        alert = SensitiveFileViolationAlert(
            alert_id=f"alert-{uuid.uuid4().hex[:12]}",
            session_id=inspection.session_id,
            target_path=inspection.target_path,
            category=matched_rule.category,
            operation_type=inspection.operation_type,
            tool_name=inspection.tool_name,
            reason=f"Attempted {inspection.operation_type.value} on protected sensitive file matching rule '{matched_rule.rule_id}'",
        )
        with self._lock:
            self._alerts.append(alert)

        logger.warning(
            "[SECURITY DENIED] File mutation blocked: %s on '%s' (Category: %s, Tool: %s)",
            inspection.operation_type,
            inspection.target_path,
            matched_rule.category,
            inspection.tool_name,
        )

        return SensitiveFileDecision(
            allowed=False,
            matched_rule=matched_rule,
            reason=f"Writing or overwriting sensitive file '{inspection.target_path}' is strictly denied ({matched_rule.description})",
            is_unlocked=False,
        )

    def assert_write_allowed(self, inspection: SensitiveFileInspection) -> None:
        """Evaluate file operation, raising PermissionDeniedSensitiveFileError if denied."""
        decision = self.inspect_file_operation(inspection)
        if not decision.allowed:
            raise PermissionDeniedSensitiveFileError(decision.reason)

    def get_alerts(
        self, session_id: str | None = None
    ) -> list[SensitiveFileViolationAlert]:
        """Retrieve security audit alerts."""
        with self._lock:
            if session_id:
                return [a for a in self._alerts if a.session_id == session_id]
            return list(self._alerts)

    def clear_alerts(self) -> None:
        """Clear all logged alerts."""
        with self._lock:
            self._alerts.clear()
