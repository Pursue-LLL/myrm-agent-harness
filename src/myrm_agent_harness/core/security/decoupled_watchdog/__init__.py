"""Decoupled action watchdog and inbound multimodal content firewall suite.

Exports the high-level suite interface and components.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .contract_invariance_asserter import ActionContractInvarianceAsserter
from .input_firewall import InboundContentFirewall
from .types import (
    ActionContractSpec,
    FirewallSanitizedPayload,
    InvarianceAssertionRule,
    ThreatSeverity,
    WatchdogInspectionResult,
    WatchdogVerdictStatus,
    WatchdogViolationDetail,
)
from .watchdog_daemon import DecoupledWatchdogDaemon


class DecoupledActionWatchdogSuite:
    """Consolidated suite combining inbound multimodal content firewall and decoupled action watchdog."""

    def __init__(self) -> None:
        self.firewall = InboundContentFirewall()
        self.watchdog = DecoupledWatchdogDaemon()

    def sanitize_inbound_content(
        self,
        raw_content: str,
        source_type: str = "web_page",
    ) -> FirewallSanitizedPayload:
        """Sanitize external content before agent observation."""
        return self.firewall.sanitize(raw_content=raw_content, source_type=source_type)

    def inspect_proposed_action(
        self,
        spec: ActionContractSpec,
        rule: InvarianceAssertionRule | None = None,
    ) -> WatchdogInspectionResult:
        """Inspect proposed action before physical invocation."""
        return self.watchdog.inspect_action(spec=spec, rule=rule)


__all__ = [
    "ActionContractInvarianceAsserter",
    "ActionContractSpec",
    "DecoupledActionWatchdogSuite",
    "DecoupledWatchdogDaemon",
    "FirewallSanitizedPayload",
    "InboundContentFirewall",
    "InvarianceAssertionRule",
    "ThreatSeverity",
    "WatchdogInspectionResult",
    "WatchdogVerdictStatus",
    "WatchdogViolationDetail",
]
