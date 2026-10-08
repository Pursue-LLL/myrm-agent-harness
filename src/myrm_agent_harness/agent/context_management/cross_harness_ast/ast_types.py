"""Canonical session state AST, cross-harness serialization, and hydration types.

[INPUT]
- None (defines pure AST types, enums, dataclasses).

[OUTPUT]
- Strongly typed representations for cross-harness session ASTs, turns, content blocks,
  tool invocations, artifact references, and hot-swap badges.

[POS]
- Harness context management in agent/context_management/cross_harness_ast/ast_types.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class AstMessageRole(str, Enum):
    """Normalized message roles across heterogeneous agent harnesses."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class HarnessTargetFormat(str, Enum):
    """Supported upstream and downstream agent harness serialization targets."""

    MYRM_NATIVE = "myrm_native"
    CLAUDE_CODE = "claude_code"
    HERMES = "hermes"
    CODEX = "codex"
    UHP_STANDARD = "uhp_standard"


@dataclass(frozen=True)
class AstContentBlock:
    """Fine-grained atomic content block within a conversation turn."""

    block_type: str  # "text", "thinking", "code", "image"
    content: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AstToolInvocation:
    """Standardized tool execution event linking call and output."""

    tool_call_id: str
    tool_name: str
    arguments: Mapping[str, str]
    result_output: str
    is_error: bool = False


@dataclass(frozen=True)
class AstArtifactRef:
    """Pointer to persistent code, chart, or data artifact created in user sandbox."""

    artifact_id: str
    file_path: str
    mime_type: str
    sha256_digest: str
    summary: str
    created_turn_id: str


@dataclass(frozen=True)
class AstTurn:
    """Individual conversational turn within the canonical AST."""

    turn_id: str
    role: AstMessageRole
    content_blocks: Sequence[AstContentBlock]
    thinking_trace: str | None = None
    tool_invocations: Sequence[AstToolInvocation] = field(default_factory=tuple)
    artifact_refs: Sequence[AstArtifactRef] = field(default_factory=tuple)
    timestamp_ms: int = 0


@dataclass(frozen=True)
class SessionStateAST:
    """Framework-agnostic Abstract Syntax Tree representing entire session context."""

    session_id: str
    created_at_ms: int
    turns: Sequence[AstTurn] = field(default_factory=tuple)
    session_metadata: Mapping[str, str] = field(default_factory=dict)
    version: str = "1.0.0"


@dataclass(frozen=True)
class ArtifactContinuityReport:
    """Audit report assessing file existence and hash integrity in sandbox storage."""

    total_artifacts: int
    verified_count: int
    missing_paths: Sequence[str] = field(default_factory=tuple)
    hash_mismatches: Sequence[str] = field(default_factory=tuple)
    is_fully_continuous: bool = True


@dataclass(frozen=True)
class ContextHealthReport:
    """Pre-flight check before hot-swapping to a target harness with different token windows."""

    estimated_tokens: int
    turn_count: int
    target_harness_limit: int
    is_compatible: bool
    compression_recommended: bool = False
    actionable_remediation: str | None = None


@dataclass(frozen=True)
class HarnessHotSwapBadge:
    """HUD status badge rendered on frontend chat stream during hot-swapping."""

    source_harness: HarnessTargetFormat
    target_harness: HarnessTargetFormat
    preserved_turns: int
    preserved_artifacts: int
    is_hot_swappable: bool
    status_message: str
