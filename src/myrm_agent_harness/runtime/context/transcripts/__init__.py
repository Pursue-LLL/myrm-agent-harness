"""Cross-tool conversation transcript parsing, remapping, and two-stage compaction.

[INPUT]
- .types::CanonicalTurnRole, CanonicalToolCall, CanonicalTranscriptTurn, TranscriptParseResult
- .path_remapper::SandboxPathRemapper, remap_path_string
- .tool_compactor::ToolOutputCompactor, compact_tool_output
- .claude_parser::ClaudeTranscriptParser
- .codex_parser::CodexTranscriptParser

[OUTPUT]
- High-fidelity transcript importers for Claude Code and Codex CLI.

[POS]
runtime/context/transcripts/__init__.py
Subsystem entrance for cross-assistant continuous conversation migration.
"""

from __future__ import annotations

from .claude_parser import ClaudeTranscriptParser
from .codex_parser import CodexTranscriptParser
from .hermes_parser import HermesTranscriptParser
from .path_remapper import SandboxPathRemapper, remap_path_string
from .tool_compactor import ToolOutputCompactor, compact_tool_output
from .types import (
    CanonicalToolCall,
    CanonicalTranscriptTurn,
    CanonicalTurnRole,
    TranscriptParseResult,
)

__all__ = [
    "CanonicalTurnRole",
    "CanonicalToolCall",
    "CanonicalTranscriptTurn",
    "TranscriptParseResult",
    "SandboxPathRemapper",
    "remap_path_string",
    "ToolOutputCompactor",
    "compact_tool_output",
    "ClaudeTranscriptParser",
    "CodexTranscriptParser",
    "HermesTranscriptParser",
]
