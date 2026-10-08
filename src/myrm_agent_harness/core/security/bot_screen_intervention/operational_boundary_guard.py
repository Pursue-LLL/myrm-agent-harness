"""
[POS] src/myrm_agent_harness/core/security/bot_screen_intervention/operational_boundary_guard.py
[INPUT] re, logging, typing, .types
[OUTPUT] BotScreenOperationalBoundaryGuard

Operational boundary guard enforcing least-privilege approval checkpoints for screen actions.
Intercepts high-risk financial, ERP, or destructive UI actions and enforces human approval gates.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re

from .types import ApprovalDecision, ScreenElementAction, ScreenRiskTier

logger = logging.getLogger(__name__)


class BotScreenOperationalBoundaryGuard:
    """Evaluates UI screen actions against operational boundaries and enterprise risk policies."""

    _DEFAULT_FINANCIAL_PATTERNS: tuple[str, ...] = (
        r"\bpay\b",
        r"\bpayment\b",
        r"\btransfer\b",
        r"\bwire\b",
        r"\bbank_account\b",
        r"\btax_submit\b",
        r"\binvoice_approve\b",
        r"\bpayout\b",
        r"\bcheckout\b",
        r"\bdisburse\b",
    )

    _DEFAULT_CRITICAL_PATTERNS: tuple[str, ...] = (
        r"\bdelete\b",
        r"\bdrop\b",
        r"\bdestroy\b",
        r"\bpurge\b",
        r"\btruncate\b",
        r"\badmin_grant\b",
        r"\brevoke_all\b",
        r"\breset_database\b",
        r"\bterminate_instance\b",
    )

    def __init__(
        self,
        custom_financial_patterns: list[str] | None = None,
        custom_critical_patterns: list[str] | None = None,
    ) -> None:
        fin_list = list(self._DEFAULT_FINANCIAL_PATTERNS)
        if custom_financial_patterns:
            fin_list.extend(custom_financial_patterns)
        self._financial_regex = re.compile("|".join(fin_list), re.IGNORECASE)

        crit_list = list(self._DEFAULT_CRITICAL_PATTERNS)
        if custom_critical_patterns:
            crit_list.extend(custom_critical_patterns)
        self._critical_regex = re.compile("|".join(crit_list), re.IGNORECASE)

    def classify_element_risk(
        self,
        selector: str,
        label: str,
        action_type: str,
    ) -> ScreenRiskTier:
        """Classify screen UI element into an appropriate operational risk tier."""
        target_text = f"{selector} {label}".lower()

        # Check critical destruction or privilege grants first
        if self._critical_regex.search(target_text):
            return ScreenRiskTier.CRITICAL_ADMIN

        # Check high-risk financial or ERP submission
        if self._financial_regex.search(target_text):
            return ScreenRiskTier.HIGH_RISK_FINANCIAL

        # Check standard mutating writes
        if action_type.lower() in ("type", "submit", "change", "click_input", "write"):
            return ScreenRiskTier.STANDARD_WRITE

        # Default to safe read-only
        return ScreenRiskTier.SAFE_READONLY

    def evaluate_action_boundary(
        self,
        action: ScreenElementAction,
    ) -> tuple[ApprovalDecision, str]:
        """Evaluate intended screen action against least-privilege boundary rules."""
        tier = action.risk_tier

        if tier == ScreenRiskTier.CRITICAL_ADMIN:
            msg = (
                f"Critical administrative or destructive action '{action.label}' "
                f"on '{action.target_selector}' requires direct manual human takeover."
            )
            logger.warning("Boundary check triggered takeover: %s", msg)
            return ApprovalDecision.MANUAL_TAKEOVER_REQUIRED, msg

        if tier == ScreenRiskTier.HIGH_RISK_FINANCIAL:
            msg = (
                f"High-risk financial/ERP action '{action.label}' "
                f"on '{action.target_selector}' requires human checkpoint approval."
            )
            logger.warning("Boundary check triggered approval checkpoint: %s", msg)
            return ApprovalDecision.PENDING_HUMAN_APPROVAL, msg

        # Standard writes and read-only actions are permitted within normal autonomous operating bounds
        logger.info(
            "Screen action '%s' on '%s' (tier: %s) automatically approved.",
            action.label,
            action.target_selector,
            tier.value,
        )
        return ApprovalDecision.APPROVED_AUTOMATIC, "Action is within safe autonomous operational boundary."
