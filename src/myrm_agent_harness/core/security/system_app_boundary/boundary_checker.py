"""
[POS] src/myrm_agent_harness/core/security/system_app_boundary/boundary_checker.py
[INPUT] types
[OUTPUT] SystemAppBoundaryChecker
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import (
    AppAccessRequest,
    AppOperationType,
    BoundaryGateDecision,
    SystemAppScopeRule,
    SystemAppType,
)

logger = logging.getLogger(__name__)


class SystemAppBoundaryChecker:
    """Enforces container scoping and emergency lockdown for local first-party applications."""

    def __init__(
        self, rules: dict[SystemAppType, SystemAppScopeRule] | None = None
    ) -> None:
        self._rules: dict[SystemAppType, SystemAppScopeRule] = dict(rules or {})

    def set_scope_rule(self, rule: SystemAppScopeRule) -> None:
        """Register or update container access boundaries for an application."""
        self._rules[rule.app_type] = rule
        logger.info("Updated scope boundary rule for app: %s", rule.app_type)

    def get_scope_rule(self, app_type: SystemAppType) -> SystemAppScopeRule:
        """Fetch declared scoping rule for app, returning default minimal-privilege rule if unset."""
        if app_type not in self._rules:
            # Default fallback: strictly no silent mutation and empty containers
            return SystemAppScopeRule(app_type=app_type)
        return self._rules[app_type]

    def lockdown_app(self, app_type: SystemAppType) -> None:
        """Place an application under emergency lockdown, denying all access immediately."""
        existing = self.get_scope_rule(app_type)
        self._rules[app_type] = SystemAppScopeRule(
            app_type=app_type,
            allowed_containers=existing.allowed_containers,
            allow_mutations_without_prompt=False,
            is_locked_down=True,
        )
        logger.warning("Emergency lockdown engaged for system app: %s", app_type)

    def unlock_app(self, app_type: SystemAppType) -> None:
        """Lift emergency lockdown from an application."""
        existing = self.get_scope_rule(app_type)
        self._rules[app_type] = SystemAppScopeRule(
            app_type=app_type,
            allowed_containers=existing.allowed_containers,
            allow_mutations_without_prompt=existing.allow_mutations_without_prompt,
            is_locked_down=False,
        )
        logger.info("Emergency lockdown released for system app: %s", app_type)

    def evaluate_request(
        self, request: AppAccessRequest
    ) -> tuple[BoundaryGateDecision, str]:
        """Assert request against container boundaries, tainted state, and operation type."""
        rule = self.get_scope_rule(request.app_type)

        # 1. Emergency lockdown check
        if rule.is_locked_down:
            return (
                BoundaryGateDecision.EMERGENCY_APP_LOCKED,
                f"Application '{request.app_type}' is under emergency lockdown",
            )

        # 2. Container scoping boundary assertion
        if rule.allowed_containers:
            target_clean = request.target_container.strip().lower()
            allowed_clean = {c.strip().lower() for c in rule.allowed_containers}
            if target_clean not in allowed_clean:
                return (
                    BoundaryGateDecision.BOUNDARY_VIOLATION_BLOCKED,
                    (
                        f"Target container '{request.target_container}' is not within "
                        f"declared whitelist for app '{request.app_type}'"
                    ),
                )

        # 3. Mutation and deletion check
        if request.operation_type in (
            AppOperationType.MUTATE_WRITE,
            AppOperationType.DELETE_PURGE,
        ):
            if request.is_external_tainted:
                return (
                    BoundaryGateDecision.REQUIRE_WRITE_CONSENT,
                    "External tainted context detected; write consent strictly required",
                )
            if not rule.allow_mutations_without_prompt:
                return (
                    BoundaryGateDecision.REQUIRE_WRITE_CONSENT,
                    f"Write/mutate operation on '{request.app_type}' requires explicit human consent",
                )
            return (
                BoundaryGateDecision.PERMITTED_SILENT,
                "Whitelisted mutation permitted silently",
            )

        # 4. Safe read-only inspection
        return (
            BoundaryGateDecision.PERMITTED_SILENT,
            "Read-only access permitted within declared container boundary",
        )
