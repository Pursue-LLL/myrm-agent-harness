"""Sandbox filesystem event probe and patch compiler.

Captures fine-grained inotify/FSEvents-style file mutations within an agent execution sandbox,
classifies critical configuration changes, and compiles tail-only diff bundles.

[INPUT]
- runtime.context.sandbox_cache_bridge_types::FileChangeKind, IncrementalPatchBundle, InvalidationScope,
  SandboxFileChangeEvent (POS: Sandbox state-aware context cache bridge types and data models.)

[OUTPUT]
- SandboxFsEventProbe: Probes and buffers fine-grained filesystem events from the sandbox.

[POS]
Sandbox filesystem event probe and patch compiler.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Mapping, Sequence

from .sandbox_cache_bridge_types import (
    FileChangeKind,
    IncrementalPatchBundle,
    InvalidationScope,
    SandboxFileChangeEvent,
)

DEFAULT_CRITICAL_CONFIG_PATTERNS: frozenset[str] = frozenset(
    {
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "AGENTS.md",
        "Makefile",
        ".env",
        "requirements.txt",
    }
)


class SandboxFsEventProbe:
    """Probes and buffers fine-grained filesystem events from the sandbox."""

    def __init__(
        self,
        critical_patterns: Sequence[str] | None = None,
    ) -> None:
        patterns = set(critical_patterns) if critical_patterns is not None else set(DEFAULT_CRITICAL_CONFIG_PATTERNS)
        self._critical_patterns: frozenset[str] = frozenset(patterns)
        self._events: list[SandboxFileChangeEvent] = []
        self._counter: int = 0

    def record_event(
        self,
        file_path: str,
        kind: FileChangeKind,
        diff_hunk: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> SandboxFileChangeEvent:
        """Capture a filesystem change event."""
        basename = os.path.basename(file_path)
        is_critical = basename in self._critical_patterns

        self._counter += 1
        event = SandboxFileChangeEvent(
            file_path=file_path,
            kind=kind,
            diff_hunk=diff_hunk,
            is_critical_config=is_critical,
            metadata=dict(metadata or {}),
            timestamp_ms=int(time.time() * 1000),
        )
        self._events.append(event)
        return event

    def has_pending_changes(self) -> bool:
        """Return True if pending filesystem events are queued."""
        return len(self._events) > 0

    def pending_count(self) -> int:
        """Return the number of queued events."""
        return len(self._events)

    def peek_events(self) -> list[SandboxFileChangeEvent]:
        """Return a shallow copy of currently buffered events."""
        return list(self._events)

    def drain_and_compile_patch(
        self,
        base_prefix_hash: str,
    ) -> IncrementalPatchBundle:
        """Compile buffered events into an IncrementalPatchBundle and clear the queue."""
        if not self._events:
            return IncrementalPatchBundle(
                patch_id=f"patch_empty_{uuid.uuid4().hex[:6]}",
                base_prefix_hash=base_prefix_hash,
                events=(),
                invalidation_scope=InvalidationScope.TAIL_PATCH_ONLY,
                formatted_tail_diff="",
                events_count=0,
                created_at_ms=int(time.time() * 1000),
            )

        events_tuple = tuple(self._events)
        has_critical = any(ev.is_critical_config for ev in events_tuple)
        scope = InvalidationScope.FULL_PREFIX_INVALIDATION if has_critical else InvalidationScope.TAIL_PATCH_ONLY

        formatted_lines: list[str] = [f"=== Sandbox Filesystem Delta ({len(events_tuple)} files) ==="]
        for ev in events_tuple:
            header = f"- [{ev.kind.value.upper()}] {ev.file_path}"
            if ev.is_critical_config:
                header += " (CRITICAL_CONFIG)"
            formatted_lines.append(header)
            if ev.diff_hunk:
                indented = "\n".join(f"  {line}" for line in ev.diff_hunk.splitlines())
                formatted_lines.append(f"  Patch:\n{indented}")

        formatted_diff = "\n".join(formatted_lines)
        patch_id = f"patch_{uuid.uuid4().hex[:8]}"

        bundle = IncrementalPatchBundle(
            patch_id=patch_id,
            base_prefix_hash=base_prefix_hash,
            events=events_tuple,
            invalidation_scope=scope,
            formatted_tail_diff=formatted_diff,
            events_count=len(events_tuple),
            created_at_ms=int(time.time() * 1000),
        )

        self._events.clear()
        return bundle
