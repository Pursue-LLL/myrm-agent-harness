"""
[INPUT]: Context chunk sources (system prompt, memory, skills, MCP, workspace files) and model snapshots.
[OUTPUT]: Immutable models for turn injection manifests, content fingerprints, and cross-turn diffs.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/turn_context_provenance/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class InjectionSourceKind(str, Enum):
    """Categorical classification of context chunks injected into an LLM call."""
    SYSTEM_PROMPT = "system_prompt"
    MEMORY = "memory"
    SKILL = "skill"
    MCP_SERVER = "mcp_server"
    WORKSPACE_FILE = "workspace_file"
    TOOL_SCHEMA = "tool_schema"


@dataclass(frozen=True)
class TurnContextChunk:
    """Immutable data record representing an individual injected context chunk."""
    chunk_id: str
    source_id: str
    kind: InjectionSourceKind
    content_sha256: str
    content_chars: int
    estimated_tokens: int
    order_index: int
    meta: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "kind": self.kind.value,
            "content_sha256": self.content_sha256,
            "content_chars": self.content_chars,
            "estimated_tokens": self.estimated_tokens,
            "order_index": self.order_index,
            "meta": dict(self.meta),
        }


@dataclass(frozen=True)
class TurnProvenanceDiffItem:
    """Represents a minimal diff for a single source across two execution turns."""
    source_id: str
    kind: InjectionSourceKind
    diff_type: str  # "ADDED" | "REMOVED" | "MODIFIED" | "UNCHANGED"
    previous_sha256: Optional[str]
    current_sha256: Optional[str]
    token_delta: int

    def to_dict(self) -> Dict[str, object]:
        return {
            "source_id": self.source_id,
            "kind": self.kind.value,
            "diff_type": self.diff_type,
            "previous_sha256": self.previous_sha256,
            "current_sha256": self.current_sha256,
            "token_delta": self.token_delta,
        }


@dataclass(frozen=True)
class TurnContextInjectionManifest:
    """Immutable turn-level injection manifest for complete reproducibility audit trails."""
    session_id: str
    turn_id: str
    chunks: List[TurnContextChunk]
    total_tokens: int
    total_chars: int
    model_snapshot_id: str
    created_at: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "chunks": [c.to_dict() for c in self.chunks],
            "total_tokens": self.total_tokens,
            "total_chars": self.total_chars,
            "model_snapshot_id": self.model_snapshot_id,
            "created_at": self.created_at,
        }
