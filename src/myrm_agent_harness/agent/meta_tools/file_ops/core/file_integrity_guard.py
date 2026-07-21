"""File integrity guard: read-before-write gate + content version matching.

Provides three complementary protections for file mutation operations:
1. Read-gate: refuses mutations on files never read in the current session.
2. Full-read gate: refuses edits after partial/range reads (marker-only).
3. Version gate: hard-rejects when on-disk content hash differs from the
   hash recorded at full-read time (external or concurrent modification).

Self-writes update the recorded hash via ``record_write`` so consecutive
edits by the same agent on content it just wrote remain allowed.

[INPUT]
- agent.middlewares._session_context::get_subagent_task_id (POS: ContextVar for subagent task ID)

[OUTPUT]
- FileIntegrityGuard: Per-executor file integrity guard (agent-aware)
- get_file_integrity_guard: Module-level factory function

[POS]
File integrity guard for sandbox file mutations. Agent-aware per-agent buckets.
Per-executor isolation via module-level factory.
"""

from __future__ import annotations

import hashlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

_DEFAULT_AGENT_ID = "__main__"


def content_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _current_agent_id() -> str:
    try:
        from myrm_agent_harness.agent.middlewares._session_context import get_subagent_task_id

        return get_subagent_task_id() or _DEFAULT_AGENT_ID
    except Exception:
        return _DEFAULT_AGENT_ID


class FileIntegrityGuard:
    """Read-gate + full-read gate + version gate for file mutations."""

    __slots__ = ("_agent_read_hashes",)

    _PARTIAL_READ_SENTINEL = ""

    def __init__(self) -> None:
        self._agent_read_hashes: dict[str, dict[str, str]] = {}

    def record_read(self, path: str, content: str, agent_id: str | None = None) -> None:
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.setdefault(aid, {})
        bucket[norm] = content_hash(content)

    def record_read_marker(self, path: str, agent_id: str | None = None) -> None:
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.setdefault(aid, {})
        if norm not in bucket:
            bucket[norm] = self._PARTIAL_READ_SENTINEL

    def record_write(self, path: str, content: str, agent_id: str | None = None) -> None:
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.setdefault(aid, {})
        bucket[norm] = content_hash(content)

    def require_read_before_write(self, path: str, agent_id: str | None = None) -> str | None:
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

    def require_full_read_before_edit(self, path: str, agent_id: str | None = None) -> str | None:
        """Reject edits when only a partial/range read marker exists."""
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.get(aid)
        if bucket is None:
            return None
        expected = bucket.get(norm)
        if expected != self._PARTIAL_READ_SENTINEL:
            return None
        return (
            f"File '{norm}' was only partially read in this session. "
            "Call file_read_tool without a line range (or read the full file) "
            "before editing, so version checking can protect against stale edits."
        )

    def require_version_match(
        self,
        path: str,
        disk_content: str,
        agent_id: str | None = None,
    ) -> str | None:
        """Hard-reject when disk content hash differs from the last full-read hash."""
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_read_hashes.get(aid)
        if bucket is None:
            return None
        expected = bucket.get(norm)
        if expected is None or expected == self._PARTIAL_READ_SENTINEL:
            return None
        current = content_hash(disk_content)
        if current == expected:
            return None
        return (
            f"File '{norm}' has changed on disk since your last read. "
            "Re-read the file with file_read_tool before editing. "
            "Your edit was blocked to prevent writing against stale content."
        )

    def clear_agent(self, agent_id: str) -> None:
        self._agent_read_hashes.pop(agent_id, None)

    def clear(self) -> None:
        self._agent_read_hashes.clear()


_integrity_guards: dict[int, FileIntegrityGuard] = {}


def get_file_integrity_guard(executor: CodeExecutor | None) -> FileIntegrityGuard | None:
    if executor is None:
        return None
    eid = id(executor)
    if eid not in _integrity_guards:
        _integrity_guards[eid] = FileIntegrityGuard()
    return _integrity_guards[eid]
