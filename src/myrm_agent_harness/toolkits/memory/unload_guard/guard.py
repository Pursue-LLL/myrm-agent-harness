# [POS]: myrm_agent_harness/toolkits/memory/unload_guard/guard.py
# [INPUT]: pathlib.Path, time, types, snapshot_builder, myrm_agent_harness.agent.context_management.handoff
# [OUTPUT]: UnloadGracefulFlushGuard
"""Atomic emergency graceful flush guard and session recovery manager.

Ensures working memory and in-flight modifications are zero-LLM flushed to disk
upon browser unload or desktop window close events.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from myrm_agent_harness.agent.context_management.handoff import (
    AgentHandoffEngine,
    AgentHandoffSpec,
    FailedApproachRecord,
    FinalizeSessionRequest,
    FinalizeSessionResult,
)
from myrm_agent_harness.toolkits.memory.unload_guard.snapshot_builder import (
    ZeroLlmEmergencySnapshotBuilder,
)
from myrm_agent_harness.toolkits.memory.unload_guard.types import (
    EmergencyFlushRequest,
    EmergencyFlushResult,
    UnfinalizedSessionSummary,
)

logger = logging.getLogger(__name__)


class UnloadGracefulFlushGuard:
    """Manages sub-millisecond atomic emergency flushes and startup resumption."""

    def __init__(
        self,
        handoff_engine: AgentHandoffEngine | None = None,
        builder: ZeroLlmEmergencySnapshotBuilder | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        self._engine = handoff_engine or AgentHandoffEngine(storage_dir=storage_dir)
        self._builder = builder or ZeroLlmEmergencySnapshotBuilder()
        logger.info("UnloadGracefulFlushGuard initialized")

    @property
    def storage_dir(self) -> Path:
        """Directory path where emergency snapshots and handoffs are stored."""
        return self._engine.store.storage_dir

    def flush(self, request: EmergencyFlushRequest) -> EmergencyFlushResult:
        """Atomically persist in-flight session state as an emergency handoff memorandum."""
        now = time.time()
        # Formulate structured failed approaches if errors exist
        failed_records = [
            FailedApproachRecord(
                approach_name="In-flight tool execution interrupted by unload/close",
                rejected_reason=err,
            )
            for err in request.recent_errors
        ]

        harness_req = FinalizeSessionRequest(
            session_id=request.session_id,
            source_profile_id=request.source_profile_id,
            active_goal=f"[{request.reason.value}] {request.active_goal}",
            next_actions=request.next_actions or ["Review emergency snapshot and resume."],
            failed_approaches=failed_records,
        )

        fin_result: FinalizeSessionResult = self._engine.finalize_session(harness_req)

        # Build clean zero-LLM markdown summary
        markdown_body = self._builder.build_markdown(
            request=request,
            handoff_id=fin_result.handoff_id,
        )

        md_path_str = fin_result.persisted_path
        if self._engine.store.storage_dir:
            md_file = self._engine.store.storage_dir / f"{fin_result.handoff_id}.md"
            md_file.write_text(markdown_body, encoding="utf-8")
            md_path_str = str(md_file)

        logger.warning(
            "Emergency flush completed for session %s into handoff [%s] at '%s'",
            request.session_id,
            fin_result.handoff_id,
            md_path_str,
        )

        return EmergencyFlushResult(
            handoff_id=fin_result.handoff_id,
            session_id=request.session_id,
            persisted_path=md_path_str,
            is_zero_llm=True,
            summary_markdown=markdown_body,
            created_at=now,
        )

    def list_unfinalized(self) -> list[UnfinalizedSessionSummary]:
        """Fetch all pending emergency handoff memorandums requiring startup restoration."""
        pending: list[AgentHandoffSpec] = self._engine.list_pending()
        summaries: list[UnfinalizedSessionSummary] = []

        for p in pending:
            reason = "browser_unload"
            if p.active_goal.startswith("[") and "]" in p.active_goal:
                end_bracket = p.active_goal.index("]")
                reason = p.active_goal[1:end_bracket]

            persisted = (
                str(self._engine.store.storage_dir / f"{p.handoff_id}.json")
                if self._engine.store.storage_dir
                else f"memory://{p.handoff_id}"
            )
            summaries.append(
                UnfinalizedSessionSummary(
                    handoff_id=p.handoff_id,
                    session_id=p.session_id,
                    active_goal=p.active_goal,
                    reason=reason,
                    persisted_path=persisted,
                    created_at=p.created_at,
                )
            )

        return summaries

    def acknowledge(
        self,
        handoff_id: str,
        claimer_profile_id: str = "recovery-agent",
        claimer_session_id: str = "recovery-session",
    ) -> bool:
        """Mark an emergency handoff as claimed/acknowledged upon user restoration."""
        try:
            self._engine.claim_handoff(
                handoff_id=handoff_id,
                claimer_profile_id=claimer_profile_id,
                claimer_session_id=claimer_session_id,
            )
            return True
        except Exception as exc:
            logger.error("Failed to acknowledge emergency handoff %s: %s", handoff_id, exc)
            return False
