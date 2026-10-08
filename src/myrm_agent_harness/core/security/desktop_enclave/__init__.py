"""Computer-Use Safe Enclave and Action Replay Audit Deck module.

[INPUT]
None.

[OUTPUT]
- DesktopActionType, DesktopActionRiskLevel
- CriticalDesktopAction, ActionEnclaveChallenge, DesktopActionAuditRecord
- DesktopActionPanickedError, CriticalActionBlockedError
- CriticalActionSemanticMatcher
- DesktopActionAuditDeck
- DesktopActionEnclaveGate

[POS]
Harness core security subsystem for Computer-Use safe enclaves.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.desktop_enclave.audit_deck import DesktopActionAuditDeck
from myrm_agent_harness.core.security.desktop_enclave.gate import DesktopActionEnclaveGate
from myrm_agent_harness.core.security.desktop_enclave.semantic_matcher import (
    CriticalActionSemanticMatcher,
)
from myrm_agent_harness.core.security.desktop_enclave.types import (
    ActionEnclaveChallenge,
    CriticalActionBlockedError,
    CriticalDesktopAction,
    DesktopActionAuditRecord,
    DesktopActionPanickedError,
    DesktopActionRiskLevel,
    DesktopActionType,
)

__all__ = [
    "DesktopActionType",
    "DesktopActionRiskLevel",
    "CriticalDesktopAction",
    "ActionEnclaveChallenge",
    "DesktopActionAuditRecord",
    "DesktopActionPanickedError",
    "CriticalActionBlockedError",
    "CriticalActionSemanticMatcher",
    "DesktopActionAuditDeck",
    "DesktopActionEnclaveGate",
]
