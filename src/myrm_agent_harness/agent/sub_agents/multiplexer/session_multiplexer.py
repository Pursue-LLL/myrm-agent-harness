"""Persistent Agent Session Multiplexer core engine.

[INPUT]
- collections::deque
- threading::RLock
- time::time
- types::(MultiplexerSession, MultiplexerSessionState, InspectSnapshot, InstructResult, AgentInstruction)

[OUTPUT]
- AgentSessionMultiplexer: Core tmux-style multiplexer managing concurrent agent sessions and inspect/instruct.
- get_session_multiplexer: Singleton provider for global harness multiplexer.

[POS]
Harness-level multiplexing engine enabling cross-agent inspection, instruction injection, and headless worker tracking.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.sub_agents.multiplexer.types import (
    AgentInstruction,
    InspectSnapshot,
    InstructResult,
    MultiplexerSession,
    MultiplexerSessionState,
)

_DEFAULT_MAX_LOG_LINES = 500


class AgentSessionMultiplexer:
    """Thread-safe persistent session multiplexer for multi-agent orchestration."""

    def __init__(self, max_log_lines: int = _DEFAULT_MAX_LOG_LINES) -> None:
        self._lock = threading.RLock()
        self._max_log_lines = max_log_lines
        self._sessions: dict[str, MultiplexerSession] = {}
        self._logs: dict[str, deque[str]] = {}
        self._instructions: dict[str, list[AgentInstruction]] = {}

    def register_session(
        self,
        session_id: str,
        agent_type: str,
        task_objective: str,
        *,
        parent_session_id: str | None = None,
        is_headless: bool = False,
        metadata: Mapping[str, object] | None = None,
    ) -> MultiplexerSession:
        """Register a new multiplexed agent session."""
        now = time.time()
        session = MultiplexerSession(
            session_id=session_id,
            parent_session_id=parent_session_id,
            agent_type=agent_type,
            task_objective=task_objective,
            state="running",
            is_headless=is_headless,
            started_at=now,
            updated_at=now,
            artifacts=[],
            metadata=dict(metadata or {}),
        )

        with self._lock:
            self._sessions[session_id] = session
            if session_id not in self._logs:
                self._logs[session_id] = deque(maxlen=self._max_log_lines)
            if session_id not in self._instructions:
                self._instructions[session_id] = []

        return session

    def unregister_session(self, session_id: str) -> bool:
        """Remove a session from multiplexer tracking."""
        with self._lock:
            removed = self._sessions.pop(session_id, None) is not None
            self._logs.pop(session_id, None)
            self._instructions.pop(session_id, None)
            return removed

    def get_session(self, session_id: str) -> MultiplexerSession | None:
        """Retrieve a session by its session_id."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(
        self,
        *,
        parent_session_id: str | None = None,
        state: MultiplexerSessionState | None = None,
        is_headless: bool | None = None,
    ) -> list[MultiplexerSession]:
        """List active sessions filtered by parent, lifecycle state, or headless flag."""
        with self._lock:
            results: list[MultiplexerSession] = []
            for sess in self._sessions.values():
                if parent_session_id is not None and sess.parent_session_id != parent_session_id:
                    continue
                if state is not None and sess.state != state:
                    continue
                if is_headless is not None and sess.is_headless != is_headless:
                    continue
                results.append(sess.model_copy())
            return results

    def update_session_state(
        self,
        session_id: str,
        state: MultiplexerSessionState,
    ) -> bool:
        """Update session lifecycle state and refresh its updated_at timestamp."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return False
            sess.state = state
            sess.updated_at = time.time()
            return True

    def append_log(self, session_id: str, log_line: str) -> None:
        """Append an execution or thought log line to the session's sliding buffer."""
        cleaned = log_line.rstrip()
        with self._lock:
            if session_id not in self._logs:
                self._logs[session_id] = deque(maxlen=self._max_log_lines)
            self._logs[session_id].append(cleaned)
            sess = self._sessions.get(session_id)
            if sess:
                sess.updated_at = time.time()

    def record_artifact(self, session_id: str, artifact_path: str) -> bool:
        """Record a generated artifact or output file path for the session."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return False
            if artifact_path not in sess.artifacts:
                sess.artifacts.append(artifact_path)
                sess.updated_at = time.time()
            return True

    def inspect_session(
        self,
        session_id: str,
        tail_lines: int = 50,
    ) -> InspectSnapshot | None:
        """Capture a read-only inspection snapshot of a concurrent agent session."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return None

            log_buffer = self._logs.get(session_id, deque())
            total_logs = len(log_buffer)
            start_idx = max(0, total_logs - tail_lines)
            slice_lines = list(log_buffer)[start_idx:]

            pending_count = sum(
                1 for inst in self._instructions.get(session_id, []) if not inst.consumed
            )

            return InspectSnapshot(
                session_id=sess.session_id,
                agent_type=sess.agent_type,
                state=sess.state,
                is_headless=sess.is_headless,
                task_objective=sess.task_objective,
                log_tail=slice_lines,
                artifacts=list(sess.artifacts),
                pending_instructions_count=pending_count,
                snapshot_timestamp=time.time(),
            )

    def inject_instruction(
        self,
        session_id: str,
        instruction: str,
        *,
        source_agent: str = "orchestrator",
    ) -> InstructResult:
        """Inject a steering or clarifying instruction into target session."""
        with self._lock:
            sess = self._sessions.get(session_id)
            if not sess:
                return InstructResult(
                    success=False,
                    session_id=session_id,
                    instruction_id="",
                    message=f"Target session '{session_id}' not found in multiplexer.",
                    queued_instructions_count=0,
                )

            inst = AgentInstruction(
                source_agent=source_agent,
                instruction=instruction.strip(),
            )
            queue = self._instructions.setdefault(session_id, [])
            queue.append(inst)
            sess.updated_at = time.time()

            unconsumed_count = sum(1 for item in queue if not item.consumed)
            return InstructResult(
                success=True,
                session_id=session_id,
                instruction_id=inst.instruction_id,
                message=f"Instruction successfully queued for '{sess.agent_type}' ({session_id}).",
                queued_instructions_count=unconsumed_count,
            )

    def consume_pending_instructions(
        self,
        session_id: str,
    ) -> Sequence[AgentInstruction]:
        """Fetch and mark as consumed all pending instructions for a session."""
        with self._lock:
            queue = self._instructions.get(session_id, [])
            pending: list[AgentInstruction] = []
            for inst in queue:
                if not inst.consumed:
                    inst.consumed = True
                    pending.append(inst.model_copy())
            return tuple(pending)


_global_multiplexer: AgentSessionMultiplexer | None = None
_global_lock = threading.Lock()


def get_session_multiplexer() -> AgentSessionMultiplexer:
    """Retrieve or create the global AgentSessionMultiplexer singleton."""
    global _global_multiplexer
    if _global_multiplexer is None:
        with _global_lock:
            if _global_multiplexer is None:
                _global_multiplexer = AgentSessionMultiplexer()
    return _global_multiplexer
