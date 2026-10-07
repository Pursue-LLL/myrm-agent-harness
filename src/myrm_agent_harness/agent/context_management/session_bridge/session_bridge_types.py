"""Strongly typed contracts for Universal Harness Session Handoff and Full-State Bridge Suite (Item 211).

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- ExternalHarnessFormat: Formats of foreign agent and web chat platforms.
- ToolExecutionTrace: Structured record preserving tool calls, outputs, and errors.
- BridgeMessageItem: Fidelity-preserving message carrying thinking, text, and tools.
- SessionWorkspaceState: Environment state carrying CWD, git diffs, and variables.
- UniversalSessionDescriptor: Lightweight metadata for UI discovery and multi-session picking.
- FullStateHandoffBundle: Complete transfer bundle carrying full state and transcript.
- ExportBridgeResult: Outcome of reverse round-trip serialization back to foreign formats.

[POS]
- Eliminates foreign harness silos, supports lossless tool and environment continuation,
- and enables bidirectional round-trip export across Claude Code, Codex, and Web AI sessions.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class ExternalHarnessFormat(str, enum.Enum):
    """Classification of external agent harnesses and export formats."""

    CLAUDE_CODE = "claude_code"
    OPENAI_CODEX = "openai_codex"
    WEB_CHAT_EXPORT = "web_chat_export"
    MYRM_NATIVE = "myrm_native"


@dataclass(frozen=True, slots=True)
class ToolExecutionTrace:
    """High-fidelity tool execution record preserving arguments, output, and execution status."""

    tool_name: str
    tool_call_id: str
    arguments: dict[str, object] = field(default_factory=dict)
    output: str = ""
    is_error: bool = False

    def to_dict(self) -> dict[str, object]:
        """Serializes tool trace to dictionary."""
        return {
            "tool_name": self.tool_name,
            "tool_call_id": self.tool_call_id,
            "arguments": dict(self.arguments),
            "output": self.output,
            "is_error": self.is_error,
        }


@dataclass(slots=True)
class BridgeMessageItem:
    """Normalized conversational turn preserving thinking, text content, and tool traces."""

    role: str
    content: str
    thinking: str = ""
    tool_traces: list[ToolExecutionTrace] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes message item to dictionary."""
        return {
            "role": self.role,
            "content": self.content,
            "thinking": self.thinking,
            "tool_traces": [t.to_dict() for t in self.tool_traces],
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class SessionWorkspaceState:
    """Operating environment state associated with the external session."""

    cwd: str = ""
    environment_vars: dict[str, str] = field(default_factory=dict)
    uncommitted_git_diff: str = ""
    git_branch: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serializes workspace state to dictionary."""
        return {
            "cwd": self.cwd,
            "environment_vars": dict(self.environment_vars),
            "uncommitted_git_diff": self.uncommitted_git_diff,
            "git_branch": self.git_branch,
        }


@dataclass(frozen=True, slots=True)
class UniversalSessionDescriptor:
    """Lightweight session profile for UI discovery drawers and precise session selection."""

    session_id: str
    format: ExternalHarnessFormat
    title: str
    turn_count: int
    message_count: int
    source_path: str = ""
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        """Serializes descriptor to dictionary."""
        return {
            "session_id": self.session_id,
            "format": self.format.value,
            "title": self.title,
            "turn_count": self.turn_count,
            "message_count": self.message_count,
            "source_path": self.source_path,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class FullStateHandoffBundle:
    """Comprehensive handoff bundle transferring entire execution state into Myrm."""

    descriptor: UniversalSessionDescriptor
    workspace_state: SessionWorkspaceState
    messages: list[BridgeMessageItem]
    accumulated_tokens: int = 0
    model_name: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serializes full-state handoff bundle to dictionary."""
        return {
            "descriptor": self.descriptor.to_dict(),
            "workspace_state": self.workspace_state.to_dict(),
            "messages": [m.to_dict() for m in self.messages],
            "accumulated_tokens": self.accumulated_tokens,
            "model_name": self.model_name,
        }


@dataclass(frozen=True, slots=True)
class ExportBridgeResult:
    """Outcome of serializing Myrm session back into external harness representations."""

    target_format: ExternalHarnessFormat
    output_payload: str
    exported_message_count: int
    export_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes export result to dictionary."""
        return {
            "target_format": self.target_format.value,
            "output_payload_bytes": len(self.output_payload.encode("utf-8")),
            "exported_message_count": self.exported_message_count,
            "export_duration_ms": self.export_duration_ms,
        }
