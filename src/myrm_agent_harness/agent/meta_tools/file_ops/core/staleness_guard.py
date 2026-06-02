"""File integrity guard: read-before-edit gate + content staleness detection.

Provides two complementary protections for file edit operations:
1. Read-gate: refuses edits on files never read in the current session,
   preventing "imagination-based" edits that fail with "text not found".
2. Staleness: detects external modifications between read and write,
   emitting a warning when file content has diverged.

[INPUT]
- agent.middlewares._session_context::get_subagent_task_id (POS: ContextVar for subagent task ID)

[OUTPUT]
- StalenessGuard: Per-executor file integrity guard (agent-aware)
- get_staleness_guard: Module-level factory function

[POS]
File integrity guard. Combines read-before-edit gate (hard reject for unread files)
with content-hash staleness detection (soft warning for externally modified files).
Agent-aware: each subagent tracks independently. Uses md5 for speed. Per-executor
isolation via module-level factory. Sentinel value ("") marks partial reads that
pass the gate but cannot provide staleness detection.
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

_DEFAULT_AGENT_ID = "__main__"


def _content_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _current_agent_id() -> str:
    """Resolve the current agent identity from ContextVar.

    Falls back to _DEFAULT_AGENT_ID when not running inside a subagent,
    preserving single-agent behaviour unchanged.
    """
    try:
        from myrm_agent_harness.agent.middlewares._session_context import get_subagent_task_id

        return get_subagent_task_id() or _DEFAULT_AGENT_ID
    except Exception:
        return _DEFAULT_AGENT_ID


class StalenessGuard:
    """File integrity guard: read-gate + staleness detection.

    Read-gate: refuses edits on files that have never been read in the
    current session, forcing the model to read before edit.

    Staleness: detects external modifications between read and write by
    comparing content hashes recorded at read time.

    Agent-aware: maintains per-agent read hashes so concurrent subagents
    cannot mask each other's state.

    Thread-safe within asyncio single-threaded model (all dict ops are
    synchronous and non-interruptible between await points).

    Sentinel convention: bucket[path] = "" means "read via range/partial"
    (passes gate, but staleness check is skipped since no full hash exists).
    """

    __slots__ = ("_agent_read_hashes",)

    _PARTIAL_READ_SENTINEL = ""

    def __init__(self) -> None:
        # {agent_id: {normalized_path: content_hash_or_sentinel}}
        self._agent_read_hashes: dict[str, dict[str, str]] = {}

    def record_read(self, path: str, content: str, agent_id: str | None = None) -> None:
        """Record the content hash at full-read time for the calling agent."""
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.setdefault(aid, {})
        bucket[norm] = _content_hash(content)

    def record_read_marker(self, path: str, agent_id: str | None = None) -> None:
        """Mark a file as 'seen' without recording a full content hash.

        Used for range/partial reads: the model has seen part of the file,
        so the read-gate should pass, but staleness detection is not possible.
        Does NOT overwrite an existing full hash (full read > partial read).
        """
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.setdefault(aid, {})
        if norm not in bucket:
            bucket[norm] = self._PARTIAL_READ_SENTINEL

    def record_write(self, path: str, content: str, agent_id: str | None = None) -> None:
        """Update the recorded hash after a successful write.

        Only updates the calling agent's own bucket so other agents'
        staleness checks remain valid.
        """
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.setdefault(aid, {})
        bucket[norm] = _content_hash(content)

    def check_staleness(self, path: str, current_content: str, agent_id: str | None = None) -> str | None:
        """Check if a file has been modified since last read.

        Args:
            path: File path (will be normalized).
            current_content: Current file content to compare against.
            agent_id: Override agent identity (auto-detected if omitted).

        Returns:
            Warning message if stale, None if unchanged, never read, or partial-read sentinel.
        """
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.get(aid)
        if bucket is None:
            return None
        expected = bucket.get(norm)
        if expected is None or expected == self._PARTIAL_READ_SENTINEL:
            return None
        current = _content_hash(current_content)
        if current == expected:
            return None
        return (
            f"\u26a0\ufe0f WARNING: File '{norm}' has been modified since your last read. "
            "The content you saw may be outdated. Verify the changes are correct."
        )

    def require_read_before_write(self, path: str, agent_id: str | None = None) -> str | None:
        """Enforce the read-before-edit gate.

        Returns None if the file has been read (full or partial) or written to
        in this session. Returns a rejection message if the file was never accessed.

        Args:
            path: File path (will be normalized).
            agent_id: Override agent identity (auto-detected if omitted).

        Returns:
            Rejection message string if file was never read, None if gate passes.
        """
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.get(aid)
        if bucket is not None and norm in bucket:
            return None
        return (
            f"File '{norm}' has not been read in this session. "
            "You must call file_read_tool to read the file before editing it, "
            "so your SEARCH text matches the actual bytes on disk."
        )

    def clear_agent(self, agent_id: str) -> None:
        """Remove all recorded hashes for a specific agent (cleanup on task completion)."""
        self._agent_read_hashes.pop(agent_id, None)

    def clear(self) -> None:
        """Clear all recorded hashes."""
        self._agent_read_hashes.clear()


# ---------------------------------------------------------------------------
# Module-level factory — one guard per executor instance
# ---------------------------------------------------------------------------

_staleness_guards: dict[int, StalenessGuard] = {}


def get_staleness_guard(executor: CodeExecutor | None) -> StalenessGuard | None:
    """Get or create a StalenessGuard for the given executor.

    Args:
        executor: The code executor bound to the current agent context.
            Returns None when no executor is available (e.g. MCP-only paths).

    Returns:
        A StalenessGuard instance shared across all agents using the same executor,
        or None if no executor is provided.
    """
    if executor is None:
        return None
    eid = id(executor)
    if eid not in _staleness_guards:
        _staleness_guards[eid] = StalenessGuard()
    return _staleness_guards[eid]
