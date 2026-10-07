"""Universal Harness Session Handoff and Full-State Bridge Suite (Item 211).

Provides multi-format external transcript parsing, high-fidelity tool execution trace retention,
CWD / git diff workspace state binding, and bidirectional round-trip export across Claude Code,
OpenAI Codex, and Web AI platforms.
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
