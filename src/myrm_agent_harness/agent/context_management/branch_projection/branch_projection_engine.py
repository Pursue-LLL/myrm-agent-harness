"""Dual-track session tree and dynamic branch projection engine.

[INPUT]
- agent.context_management.branch_projection.branch_projection_types::BranchSummary, EntryKind,
  OperationStatus, ProjectedContext, SessionEntry, SessionOperation, TokenUsage (POS: Types and data contracts
  for dual-track session tree and dynamic branch projection.)
- agent.context_management.branch_projection.lca_branch_summarizer::collect_departed_entries, find_lca,
  synthesize_branch_delta_summary (POS: LCA branch discovery and delta summarization for lossless cross-branch
  transitions.)

[OUTPUT]
- DualTrackBranchProjectionEngine: Manages dual-track storage, zero-copy forking, LCA summarization, and projection.

[POS]
Core execution engine for dual-track session tree and dynamic branch working set projection.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Mapping, Sequence

from .branch_projection_types import (
    BranchSummary,
    EntryKind,
    OperationStatus,
    ProjectedContext,
    SessionEntry,
    SessionOperation,
    TokenUsage,
)
from .lca_branch_summarizer import (
    collect_departed_entries,
    find_lca,
    synthesize_branch_delta_summary,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-3-7-sonnet"
DEFAULT_THINKING_LEVEL = "high"


class DualTrackBranchProjectionEngine:
    """Manages dual-track session entries, runtime operations, and dynamic branch context projection."""

    def __init__(self) -> None:
        self._entries: dict[str, SessionEntry] = {}
        self._operations: list[SessionOperation] = []
        self._branch_leaves: dict[str, str | None] = {}
        self._branch_names: dict[str, str] = {}
        self._branch_sessions: dict[str, str] = {}
        self._session_branches: dict[str, set[str]] = {}
        self._seq_counters: dict[str, int] = {}

    def create_session(
        self,
        session_id: str,
        root_branch_name: str = "main",
    ) -> str:
        """Initialize a new session tree with a root branch and return root branch_id."""
        branch_id = f"br-{uuid.uuid4().hex[:8]}"
        self._branch_leaves[branch_id] = None
        self._branch_names[branch_id] = root_branch_name
        self._branch_sessions[branch_id] = session_id
        self._session_branches.setdefault(session_id, set()).add(branch_id)
        self._seq_counters[session_id] = 0

        logger.info("Initialized session '%s' with root branch '%s' (%s)", session_id, root_branch_name, branch_id)
        return branch_id

    def record_entry(
        self,
        session_id: str,
        branch_id: str,
        kind: EntryKind,
        payload: Mapping[str, str],
        metadata: Mapping[str, str] | None = None,
    ) -> SessionEntry:
        """Append an immutable domain fact entry to the active branch leaf."""
        if branch_id not in self._branch_leaves:
            raise KeyError(f"Branch '{branch_id}' does not exist.")

        parent_id = self._branch_leaves[branch_id]
        seq = self._seq_counters.get(session_id, 0) + 1
        self._seq_counters[session_id] = seq

        entry_id = f"ent-{uuid.uuid4().hex[:10]}"
        entry = SessionEntry(
            entry_id=entry_id,
            parent_id=parent_id,
            session_id=session_id,
            branch_id=branch_id,
            seq=seq,
            kind=kind,
            payload=dict(payload),
            metadata=dict(metadata or {}),
            created_at_iso=datetime.now(timezone.utc).isoformat(),
        )

        self._entries[entry_id] = entry
        self._branch_leaves[branch_id] = entry_id
        return entry

    def record_operation(self, operation: SessionOperation) -> None:
        """Record runtime operational telemetry into the out-of-band ledger."""
        self._operations.append(operation)

    def get_operations(
        self,
        session_id: str,
        branch_id: str | None = None,
    ) -> tuple[SessionOperation, ...]:
        """Query runtime operational telemetry records for a session or branch."""
        ops = [
            op
            for op in self._operations
            if op.session_id == session_id
            and (branch_id is None or op.branch_id == branch_id)
        ]
        return tuple(ops)

    def fork_branch(
        self,
        source_branch_id: str,
        new_branch_name: str,
        at_entry_id: str | None = None,
    ) -> str:
        """Fork a new branch in O(1) time without copying historical data."""
        if source_branch_id not in self._branch_leaves:
            raise KeyError(f"Source branch '{source_branch_id}' does not exist.")

        session_id = self._branch_sessions[source_branch_id]
        fork_anchor_id = (
            at_entry_id
            if at_entry_id is not None
            else self._branch_leaves[source_branch_id]
        )

        if fork_anchor_id is not None and fork_anchor_id not in self._entries:
            raise KeyError(f"Anchor entry '{fork_anchor_id}' does not exist.")

        new_branch_id = f"br-{uuid.uuid4().hex[:8]}"
        self._branch_leaves[new_branch_id] = fork_anchor_id
        self._branch_names[new_branch_id] = new_branch_name
        self._branch_sessions[new_branch_id] = session_id
        self._session_branches.setdefault(session_id, set()).add(new_branch_id)

        logger.info(
            "Forked branch '%s' (%s) from '%s' at anchor '%s'",
            new_branch_name,
            new_branch_id,
            source_branch_id,
            fork_anchor_id,
        )
        return new_branch_id

    def switch_branch(
        self,
        from_branch_id: str,
        to_branch_id: str,
        inject_summary_to_target: bool = True,
    ) -> BranchSummary | None:
        """Switch active branch, calculate LCA delta summary, and optionally inject to target."""
        if from_branch_id not in self._branch_leaves:
            raise KeyError(f"Source branch '{from_branch_id}' not found.")
        if to_branch_id not in self._branch_leaves:
            raise KeyError(f"Destination branch '{to_branch_id}' not found.")

        leaf_from = self._branch_leaves[from_branch_id]
        leaf_to = self._branch_leaves[to_branch_id]

        if leaf_from is None or leaf_to is None:
            return None

        lca_id = find_lca(self._entries, leaf_from, leaf_to)
        if lca_id is None:
            logger.warning("No common ancestor found between %s and %s", from_branch_id, to_branch_id)
            return None

        departed = collect_departed_entries(self._entries, leaf_from, lca_id)
        if not departed:
            return None

        summary = synthesize_branch_delta_summary(
            departed_entries=departed,
            source_branch_id=from_branch_id,
            target_branch_id=to_branch_id,
            lca_entry_id=lca_id,
        )

        if inject_summary_to_target:
            session_id = self._branch_sessions[to_branch_id]
            self.record_entry(
                session_id=session_id,
                branch_id=to_branch_id,
                kind=EntryKind.BRANCH_SUMMARY,
                payload={
                    "source_branch_id": from_branch_id,
                    "target_branch_id": to_branch_id,
                    "lca_entry_id": lca_id,
                    "summary_text": summary.summary_text,
                    "read_files": ",".join(summary.read_files),
                    "modified_files": ",".join(summary.modified_files),
                },
                metadata={"injected_from_switch": "true"},
            )

        return summary

    def build_context_projection(self, branch_id: str) -> ProjectedContext:
        """Project the working set context from the current branch leaf back to the root."""
        if branch_id not in self._branch_leaves:
            raise KeyError(f"Branch '{branch_id}' not found.")

        leaf_id = self._branch_leaves[branch_id]
        session_id = self._branch_sessions[branch_id]

        if leaf_id is None:
            return ProjectedContext(
                session_id=session_id,
                branch_id=branch_id,
                leaf_entry_id="",
                lineage_entry_ids=(),
                effective_model=DEFAULT_MODEL,
                effective_thinking_level=DEFAULT_THINKING_LEVEL,
                effective_active_tools=(),
                projected_messages=(),
                total_projected_entries=0,
            )

        lineage_entries: list[SessionEntry] = []
        curr: str | None = leaf_id
        while curr is not None:
            entry = self._entries.get(curr)
            if entry is None:
                break
            lineage_entries.append(entry)
            curr = entry.parent_id

        # Reverse to chronological order (root to leaf)
        lineage_entries.reverse()

        effective_model = DEFAULT_MODEL
        effective_thinking = DEFAULT_THINKING_LEVEL
        effective_tools: tuple[str, ...] = ()
        messages: list[dict[str, str]] = []

        for ent in lineage_entries:
            if ent.kind == EntryKind.MODEL_CHANGE:
                effective_model = ent.payload.get("model", effective_model)
            elif ent.kind == EntryKind.THINKING_LEVEL:
                effective_thinking = ent.payload.get("thinking_level", effective_thinking)
            elif ent.kind == EntryKind.ACTIVE_TOOLS:
                tools_str = ent.payload.get("tools", "")
                if tools_str:
                    effective_tools = tuple(t.strip() for t in tools_str.split(",") if t.strip())
            elif ent.kind == EntryKind.MESSAGE:
                role = ent.payload.get("role", "user")
                content = ent.payload.get("content", "")
                messages.append({"role": role, "content": content})
            elif ent.kind == EntryKind.COMPACTION:
                summary_text = ent.payload.get("summary", "")
                messages.append({
                    "role": "system",
                    "content": f"[Context Compacted] {summary_text}",
                })
            elif ent.kind == EntryKind.BRANCH_SUMMARY:
                summary_text = ent.payload.get("summary_text", "")
                messages.append({
                    "role": "system",
                    "content": f"[Cross-Branch Exploration Context] {summary_text}",
                })

        return ProjectedContext(
            session_id=session_id,
            branch_id=branch_id,
            leaf_entry_id=leaf_id,
            lineage_entry_ids=tuple(e.entry_id for e in lineage_entries),
            effective_model=effective_model,
            effective_thinking_level=effective_thinking,
            effective_active_tools=effective_tools,
            projected_messages=tuple(messages),
            total_projected_entries=len(lineage_entries),
        )

    def get_branch_topology(self, session_id: str) -> dict[str, str]:
        """Return a mapping of branch_id to branch_name for the session."""
        branches = self._session_branches.get(session_id, set())
        return {b_id: self._branch_names.get(b_id, "") for b_id in branches}
