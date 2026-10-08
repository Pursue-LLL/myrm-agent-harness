# [INPUT]: None
# [OUTPUT]: ClarifyCardEngine, ClarifyCardPayload, ClarifyCardStatus, ClarifyDispatchReceipt, ClarifyOptionItem, ClarifyResponsePath, HermesDesktopClarifyCardsSuite, create_clarify_card
# [POS]: agent/context_management/clarify_cards/__init__.py

"""Clarification cards subsystem for interactive question rendering, answering, expiration, and input interception.

[INPUT]
- None (Public package entry point).

[OUTPUT]
- ClarifyCardEngine: State machine and storage registry for interactive clarify cards.
- ClarifyCardPayload: Canonical data model capturing clarification question cards.
- ClarifyCardStatus: Lifecycle status enum (pending, answered, expired, invalidated).
- ClarifyDispatchReceipt: Cryptographically verifiable receipt for clarification lifecycle events.
- ClarifyOptionItem: Discrete selectable choice item.
- ClarifyResponsePath: UI routing channel enum.
- HermesDesktopClarifyCardsSuite: Unified facade managing clarify card rendering, answering, and interception.
- create_clarify_card: Convenience builder creating ClarifyCardPayload.

[POS]
Package entry point for Hermes Desktop clarification cards subsystem.
"""

from __future__ import annotations

from .clarify_card_engine import ClarifyCardEngine
from .clarify_card_types import (
    ClarifyCardPayload,
    ClarifyCardStatus,
    ClarifyDispatchReceipt,
    ClarifyOptionItem,
    ClarifyResponsePath,
)
from .hermes_desktop_clarify_suite import (
    HermesDesktopClarifyCardsSuite,
    create_clarify_card,
)

__all__ = [
    "ClarifyCardEngine",
    "ClarifyCardPayload",
    "ClarifyCardStatus",
    "ClarifyDispatchReceipt",
    "ClarifyOptionItem",
    "ClarifyResponsePath",
    "HermesDesktopClarifyCardsSuite",
    "create_clarify_card",
]
