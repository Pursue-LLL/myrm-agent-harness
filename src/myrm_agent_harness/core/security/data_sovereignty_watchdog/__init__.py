"""
[POS] src/myrm_agent_harness/core/security/data_sovereignty_watchdog/__init__.py
[INPUT] .facade, .types
[OUTPUT] DataSovereigntyWatchdogSuite, SandboxSovereigntySeal, SubIntrusiveWatchdog, HighStakesConsentGate, ...

Private Sandbox Data Sovereignty & Sub-Intrusive Proactivity Watchdog Suite.
Ensures zero-central-cloud retention of financial/email data, suppresses low-value noise,
and guards high-stakes financial operations behind one-time human consent gates.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import DataSovereigntyWatchdogSuite
from .high_stakes_consent_gate import HighStakesConsentGate
from .sovereignty_seal import SandboxSovereigntySeal
from .sub_intrusive_watchdog import SubIntrusiveWatchdog
from .types import (
    DataSovereigntyWatchdogMetrics,
    HighStakesActionType,
    HighStakesConsentTicket,
    ProactivityValueLevel,
    SovereigntySealLevel,
    SovereigntySealManifest,
    SubIntrusiveNotificationCard,
)

__all__ = [
    "DataSovereigntyWatchdogMetrics",
    "DataSovereigntyWatchdogSuite",
    "HighStakesActionType",
    "HighStakesConsentTicket",
    "HighStakesConsentGate",
    "ProactivityValueLevel",
    "SandboxSovereigntySeal",
    "SovereigntySealLevel",
    "SovereigntySealManifest",
    "SubIntrusiveNotificationCard",
    "SubIntrusiveWatchdog",
]
