"""Universal Harness Session Handoff and Full-State Bridge Suite (Item 211).

Provides multi-format external transcript parsing, high-fidelity tool execution trace retention,
CWD / git diff workspace state binding, and bidirectional round-trip export across Claude Code,
OpenAI Codex, and Web AI platforms.

[INPUT]
- agent.context_management.session_bridge.session_bridge_engine::UniversalSessionBridgeEngine (POS: Universal
  Harness Session Handoff and Full-State Bridge Engine (Item 211).)
- agent.context_management.session_bridge.session_bridge_exporter::SessionBridgeExporter (POS: Reverse export
  serialization bridge for external agent formats (Item 211).)
- agent.context_management.session_bridge.session_bridge_types::BridgeMessageItem, ExportBridgeResult,
  ExternalHarnessFormat, FullStateHandoffBundle, SessionWorkspaceState, ToolExecutionTrace,
  UniversalSessionDescriptor (POS: Strongly typed contracts for Universal Harness Session Handoff and
  Full-State Bridge Suite (Item 211).)

[OUTPUT]
- Re-exports: BridgeMessageItem, ExportBridgeResult, ExternalHarnessFormat, FullStateHandoffBundle,
  SessionBridgeExporter, SessionWorkspaceState, ToolExecutionTrace, UniversalSessionBridgeEngine,
  UniversalSessionDescriptor

[POS]
Universal Harness Session Handoff and Full-State Bridge Suite (Item 211).
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_engine import (
    UniversalSessionBridgeEngine,
)
from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_exporter import (
    SessionBridgeExporter,
)
from myrm_agent_harness.agent.context_management.session_bridge.session_bridge_types import (
    BridgeMessageItem,
    ExportBridgeResult,
    ExternalHarnessFormat,
    FullStateHandoffBundle,
    SessionWorkspaceState,
    ToolExecutionTrace,
    UniversalSessionDescriptor,
)

__all__ = [
    "BridgeMessageItem",
    "ExportBridgeResult",
    "ExternalHarnessFormat",
    "FullStateHandoffBundle",
    "SessionBridgeExporter",
    "SessionWorkspaceState",
    "ToolExecutionTrace",
    "UniversalSessionBridgeEngine",
    "UniversalSessionDescriptor",
]
