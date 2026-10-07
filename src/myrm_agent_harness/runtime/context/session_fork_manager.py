"""Session fork manager and background pipe-back pipeline.

Orchestrates non-blocking background sessions (/bg) and context snapshot forks (/btw),
safely piping asynchronously produced results back to the parent session.

[INPUT]
- runtime.context.session_fork_steer_types::BackgroundForkDescriptor, ForkCommandKind, ForkSessionState,
  PipeBackPayload (POS: Session fork and in-flight steer control types.)

[OUTPUT]
- SessionForkManager: Manages background session life cycles and pipes completed outputs back.

[POS]
Session fork manager and background pipe-back pipeline.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence

from .session_fork_steer_types import (
    BackgroundForkDescriptor,
    ForkCommandKind,
    ForkSessionState,
    PipeBackPayload,
)


class SessionForkManager:
    """Manages background session life cycles and pipes completed outputs back."""

    def __init__(self) -> None:
        self._forks: dict[str, BackgroundForkDescriptor] = {}
        self._pipe_back_queue: list[PipeBackPayload] = []

    def create_bg_fork(
        self,
        parent_session_id: str,
        prompt: str,
        metadata: Mapping[str, str] | None = None,
    ) -> BackgroundForkDescriptor:
        """Spawn a completely clean, isolated background session."""
        fork_id = f"bg_{uuid.uuid4().hex[:8]}"
        descriptor = BackgroundForkDescriptor(
            fork_id=fork_id,
            parent_session_id=parent_session_id,
            kind=ForkCommandKind.BG,
            prompt=prompt,
            state=ForkSessionState.STAGED,
            snapshot_context=None,
            created_at_ms=int(time.time() * 1000),
            metadata=dict(metadata or {}),
        )
        self._forks[fork_id] = descriptor
        return descriptor

    def create_btw_fork(
        self,
        parent_session_id: str,
        prompt: str,
        snapshot_context: str,
        metadata: Mapping[str, str] | None = None,
    ) -> BackgroundForkDescriptor:
        """Spawn a background fork holding a read-only snapshot of parent context."""
        fork_id = f"btw_{uuid.uuid4().hex[:8]}"
        descriptor = BackgroundForkDescriptor(
            fork_id=fork_id,
            parent_session_id=parent_session_id,
            kind=ForkCommandKind.BTW,
            prompt=prompt,
            state=ForkSessionState.STAGED,
            snapshot_context=snapshot_context,
            created_at_ms=int(time.time() * 1000),
            metadata=dict(metadata or {}),
        )
        self._forks[fork_id] = descriptor
        return descriptor

    def get_fork(self, fork_id: str) -> BackgroundForkDescriptor | None:
        """Retrieve descriptor of a fork by ID."""
        return self._forks.get(fork_id)

    def get_active_forks(self, parent_session_id: str) -> list[BackgroundForkDescriptor]:
        """Return all non-terminated forks associated with parent_session_id."""
        return [
            f
            for f in self._forks.values()
            if f.parent_session_id == parent_session_id
            and f.state in (ForkSessionState.STAGED, ForkSessionState.RUNNING)
        ]

    def update_fork_state(
        self,
        fork_id: str,
        state: ForkSessionState,
        result_summary: str | None = None,
        artifacts: Sequence[str] | None = None,
    ) -> BackgroundForkDescriptor:
        """Transition fork state and stage pipe-back payload upon completion."""
        current = self._forks.get(fork_id)
        if current is None:
            raise KeyError(f"Fork session '{fork_id}' not found.")

        now_ms = int(time.time() * 1000)
        completed_at = (
            now_ms
            if state in (ForkSessionState.COMPLETED, ForkSessionState.FAILED, ForkSessionState.CANCELLED)
            else current.completed_at_ms
        )

        updated = BackgroundForkDescriptor(
            fork_id=current.fork_id,
            parent_session_id=current.parent_session_id,
            kind=current.kind,
            prompt=current.prompt,
            state=state,
            snapshot_context=current.snapshot_context,
            result_summary=result_summary if result_summary is not None else current.result_summary,
            created_at_ms=current.created_at_ms,
            completed_at_ms=completed_at,
            metadata=current.metadata,
        )
        self._forks[fork_id] = updated

        # If terminal state, assemble and stage pipe-back payload
        if state in (ForkSessionState.COMPLETED, ForkSessionState.FAILED):
            pipe_payload = PipeBackPayload(
                pipe_id=f"pipe_{uuid.uuid4().hex[:8]}",
                fork_id=current.fork_id,
                parent_session_id=current.parent_session_id,
                kind=current.kind,
                output_content=result_summary or "",
                status=state,
                artifacts=tuple(artifacts or ()),
                piped_at_ms=now_ms,
            )
            self._pipe_back_queue.append(pipe_payload)

        return updated

    def cancel_fork(self, fork_id: str) -> BackgroundForkDescriptor | None:
        """Cancel a running or staged fork session."""
        if fork_id in self._forks:
            return self.update_fork_state(
                fork_id=fork_id,
                state=ForkSessionState.CANCELLED,
                result_summary="User cancelled background task.",
            )
        return None

    def drain_pipe_back_events(self, parent_session_id: str) -> list[PipeBackPayload]:
        """Drain and return all queued pipe-back results targeting parent_session_id."""
        matching: list[PipeBackPayload] = []
        remaining: list[PipeBackPayload] = []

        for payload in self._pipe_back_queue:
            if payload.parent_session_id == parent_session_id:
                matching.append(payload)
            else:
                remaining.append(payload)

        self._pipe_back_queue = remaining
        return matching
