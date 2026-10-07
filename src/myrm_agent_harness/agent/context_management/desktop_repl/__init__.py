"""Persistent Scriptable REPL Desktop Session and Multi-Step Batch Execution Suite (Item 204).

Enables state-retaining persistent REPL sessions for desktop computer use,
in-memory multi-step script execution, cross-turn variable caching, and fast repl_reset.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.desktop_repl.desktop_repl_engine import (
    DesktopApiSdk,
    DesktopElementMock,
    PersistentDesktopReplEngine,
)
from myrm_agent_harness.agent.context_management.desktop_repl.desktop_repl_types import (
    DesktopReplSessionSnapshot,
    ReplExecutionResult,
    ReplExecutionStatus,
    ReplRuntimeKind,
    ReplScriptCommand,
)

__all__ = [
    "DesktopApiSdk",
    "DesktopElementMock",
    "DesktopReplSessionSnapshot",
    "PersistentDesktopReplEngine",
    "ReplExecutionResult",
    "ReplExecutionStatus",
    "ReplRuntimeKind",
    "ReplScriptCommand",
]
