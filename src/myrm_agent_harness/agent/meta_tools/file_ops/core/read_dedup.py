"""Read dedup guard: skip re-reading unchanged files to protect Prompt Cache.

Long sessions often re-read the same file (config, docs, code) across turns.
Each re-read emits a fresh ToolMessage with identical content, which:
1. Wastes context tokens (the content is already in the conversation).
2. Shifts the message sequence, lowering Prompt Cache hit rate.

The existing ``deduplicate_tool_results`` (context_management) only cleans up
*after* the fact, during compression — the duplicate content already occupied
context and compression itself breaks the cache. This guard works *before* the
read: when a file is unchanged since the last read of the same (path, range),
it returns a lightweight stub instead of re-sending the content, keeping the
message sequence stable and the cache hot.

Design notes:
- Per-executor isolation via a module-level registry (mirrors FileIntegrityGuard).
- Only applies to local files where mtime is stat-able; cloud/MCP/vault paths
  skip dedup (no reliable mtime).
- A stub hit still counts toward a hard block: after N consecutive stubs for
  the same key, we hard-block to stop weak tool-followers from looping.
- ``invalidate`` is called after a write so a just-edited file is re-read.
- ``reset`` is called after context compression so the model re-reads content
  that was summarised away.
- Env kill-switch ``MYRM_READ_DEDUP_ENABLED`` (default on) for emergencies.

[INPUT]
- agent.middlewares._session_context::get_subagent_task_id (POS: ContextVar for subagent task ID)

[OUTPUT]
- ReadDedupGuard: per-executor read dedup guard (agent-aware)
- get_read_dedup_guard: Module-level factory function
- reset_all_read_dedup: Global reset (context compression hook)

[POS]
Read dedup guard for sandbox file reads. Agent-aware per-agent buckets.
Per-executor isolation via module-level factory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

_DEFAULT_AGENT_ID = "__main__"

# Hard-block after this many consecutive stub hits for the same key.
_DEDUP_BLOCK_THRESHOLD = 2

_ENV_KILL_SWITCH = "MYRM_READ_DEDUP_ENABLED"


def _dedup_enabled() -> bool:
    return os.environ.get(_ENV_KILL_SWITCH, "1") != "0"


def _current_agent_id() -> str:
    try:
        from myrm_agent_harness.agent.middlewares._session_context import get_subagent_task_id

        return get_subagent_task_id() or _DEFAULT_AGENT_ID
    except Exception:
        return _DEFAULT_AGENT_ID


@dataclass(frozen=True)
class DedupEntry:
    """Recorded state for one (path, range) read key."""

    mtime: float
    hits: int


class DedupResult:
    """Outcome of a dedup check."""

    __slots__ = ("hits", "kind")

    MISS = "miss"
    STUB = "stub"
    BLOCKED = "blocked"

    def __init__(self, kind: str, hits: int = 0) -> None:
        self.kind = kind
        self.hits = hits

    @property
    def is_hit(self) -> bool:
        return self.kind in (self.STUB, self.BLOCKED)


class ReadDedupGuard:
    """Per-agent read dedup with stub + hard-block escalation."""

    __slots__ = ("_agent_dedup",)

    def __init__(self) -> None:
        self._agent_dedup: dict[str, dict[tuple[str, str], DedupEntry]] = {}

    def check(
        self,
        path: str,
        view_range: str | None,
        mtime: float,
        agent_id: str | None = None,
    ) -> DedupResult:
        """Check whether a read of ``path`` at ``view_range`` is a duplicate.

        Returns ``MISS`` when the file changed or was never read, ``STUB`` on
        the first duplicate (content unchanged), and ``BLOCKED`` after
        ``_DEDUP_BLOCK_THRESHOLD`` consecutive duplicates.
        """
        if not _dedup_enabled():
            return DedupResult(DedupResult.MISS)

        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        key = (norm, view_range or "")
        bucket = self._agent_dedup.setdefault(aid, {})

        entry = bucket.get(key)
        if entry is None or entry.mtime != mtime:
            # First read of this key, or the file changed since last read.
            bucket[key] = DedupEntry(mtime=mtime, hits=0)
            return DedupResult(DedupResult.MISS)

        hits = entry.hits + 1
        bucket[key] = DedupEntry(mtime=entry.mtime, hits=hits)
        if hits >= _DEDUP_BLOCK_THRESHOLD:
            return DedupResult(DedupResult.BLOCKED, hits=hits)
        return DedupResult(DedupResult.STUB, hits=hits)

    def invalidate(self, path: str, agent_id: str | None = None) -> None:
        """Drop dedup state for ``path`` after a write so it is re-read."""
        aid = agent_id or _current_agent_id()
        norm = os.path.normpath(path)
        bucket = self._agent_dedup.get(aid)
        if bucket is None:
            return
        for key in [k for k in bucket if k[0] == norm]:
            bucket.pop(key, None)

    def clear_agent(self, agent_id: str) -> None:
        self._agent_dedup.pop(agent_id, None)

    def clear(self) -> None:
        self._agent_dedup.clear()


_dedup_guards: dict[int, ReadDedupGuard] = {}


def get_read_dedup_guard(executor: CodeExecutor | None) -> ReadDedupGuard | None:
    if executor is None:
        return None
    eid = id(executor)
    if eid not in _dedup_guards:
        _dedup_guards[eid] = ReadDedupGuard()
    return _dedup_guards[eid]


def reset_all_read_dedup() -> None:
    """Clear every executor's dedup state (called after context compression)."""
    for guard in _dedup_guards.values():
        guard.clear()
