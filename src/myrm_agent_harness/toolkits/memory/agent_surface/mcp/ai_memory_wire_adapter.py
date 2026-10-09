"""Wire-format adapter emulating the 5.3k Star ai-memory MCP tool protocol.

Provides drop-in wire compatibility for external agents (Claude Code, Cursor, Codex)
while internally routing into Myrm's typed AgentHandoffEngine and MemoryPrivacyBoundaryGate.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.handoff::AgentHandoffEngine, FailedApproachRecord, FinalizeSessionRequest (POS:
  Public interface for agent handoff management and session finalization.)
- toolkits.memory.agent_surface.mcp.types::AiMemoryFinalizeRequest, AiMemoryQueryRequest,
  AiMemoryRememberRequest (POS: Data models for ai-memory wire format interoperability and cross-tool MCP
  gateway.)
- toolkits.memory.privacy_gate::MemoryPrivacyBoundaryGate, PrivacyCheckResult (POS: Public entry point for
  memory privacy boundary and allowlist gate.)

[OUTPUT]
- AiMemoryWireAdapter: Wire adapter providing full signature and format parity with ai-memory.

[POS]
Wire-format adapter emulating the 5.3k Star ai-memory MCP tool protocol.
"""

from __future__ import annotations

import logging
import time

from myrm_agent_harness.toolkits.memory.agent_surface.mcp.types import (
    AiMemoryFinalizeRequest,
    AiMemoryQueryRequest,
    AiMemoryRememberRequest,
)
from myrm_agent_harness.toolkits.memory.handoff import (
    AgentHandoffEngine,
    FailedApproachRecord,
    FinalizeSessionRequest,
)
from myrm_agent_harness.toolkits.memory.privacy_gate import (
    MemoryPrivacyBoundaryGate,
    PrivacyCheckResult,
)

logger = logging.getLogger(__name__)


class AiMemoryWireAdapter:
    """Wire adapter providing full signature and format parity with ai-memory."""

    def __init__(
        self,
        handoff_engine: AgentHandoffEngine | None = None,
        privacy_gate: MemoryPrivacyBoundaryGate | None = None,
    ) -> None:
        self._handoff_engine = handoff_engine or AgentHandoffEngine()
        self._privacy_gate = privacy_gate or MemoryPrivacyBoundaryGate()
        self._mock_memory_store: dict[str, list[str]] = {}

    def query_memory(self, query: str, limit: int = 5) -> str:
        """Query memory facts and knowledge base, returning ai-memory formatted markdown."""
        req = AiMemoryQueryRequest(query=query, limit=limit)
        clean_q = req.query.lower().strip()

        matched_lines: list[str] = []
        for topic, notes in self._mock_memory_store.items():
            if clean_q in topic.lower():
                for note in notes:
                    matched_lines.append(f"- **[{topic}]** {note}")
            else:
                for note in notes:
                    if clean_q in note.lower():
                        matched_lines.append(f"- **[{topic}]** {note}")

        if not matched_lines:
            return f'### Memory Search: "{req.query}"\n\nNo matching memories found.'

        selected = matched_lines[: req.limit]
        body = "\n".join(selected)
        return f'### Memory Search: "{req.query}" ({len(selected)} results)\n\n{body}'

    def get_handoff(self, target_profile_id: str | None = None) -> str:
        """Fetch active pending handoff memorandum formatted as human-readable markdown."""
        pending_list = self._handoff_engine.list_pending(target_profile_id=target_profile_id)
        if not pending_list:
            return "No pending handoff memorandum found. Ready for fresh execution."

        spec = pending_list[0]
        lines: list[str] = [
            f"## Active Handoff Memorandum [{spec.handoff_id}]",
            f"- **Source Agent:** {spec.source_profile_id}",
            f"- **Target Agent:** {spec.target_profile_id or 'any'}",
            f"- **Active Goal:** {spec.active_goal}",
            "",
            "### Immediate Next Actions",
        ]
        if spec.next_actions:
            lines.extend(f"{idx + 1}. {act}" for idx, act in enumerate(spec.next_actions))
        else:
            lines.append("No explicit next actions defined.")

        if spec.failed_approaches:
            lines.extend(["", "### Discarded Hypotheses & Pitfalls"])
            for fa in spec.failed_approaches:
                lines.append(f"- **Avoid:** {fa.approach_name} — Reason: {fa.rejected_reason}")

        if spec.implicit_constraints:
            lines.extend(["", "### Implicit Business Constraints"])
            for ic in spec.implicit_constraints:
                lines.append(f"- **[{ic.scope}]** {ic.constraint_rule} ({ic.rationale})")

        return "\n".join(lines)

    def finalize_session(
        self,
        summary: str,
        next_steps: list[str],
        failed_approaches: list[str] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Finalize working session and write durable handoff memorandum to Myrm storage."""
        req = AiMemoryFinalizeRequest(
            session_id=session_id or f"mcp-session-{int(time.time())}",
            summary=summary,
            next_steps=next_steps,
            failed_approaches=failed_approaches or [],
        )

        h_req = FinalizeSessionRequest(
            session_id=req.session_id,
            source_profile_id=req.source_profile_id,
            active_goal=req.summary,
            next_actions=req.next_steps,
            failed_approaches=[
                FailedApproachRecord(
                    approach_name=item,
                    rejected_reason="Recorded via external MCP finalize_session call",
                )
                for item in req.failed_approaches
            ],
        )

        res = self._handoff_engine.finalize_session(h_req)
        return (
            f"Session finalized successfully into durable memorandum [{res.handoff_id}] "
            f"at '{res.persisted_path}'. Ready for successor agent pickup."
        )

    def remember(self, topic: str, note: str, source_file: str | None = None) -> str:
        """Ingest new fact under mandatory privacy boundary gate inspection."""
        req = AiMemoryRememberRequest(topic=topic, note=note, source_file=source_file)

        # Mandatory Privacy Boundary Check
        check_res: PrivacyCheckResult = self._privacy_gate.check(
            content=req.note,
            source_path=req.source_file,
        )
        if not check_res.passed:
            logger.warning("Rejected external MCP memory ingestion: %s", check_res.violation_reason)
            return (
                f"REJECTED by Privacy Boundary Gate: {check_res.violation_reason}. "
                "Secrets or prohibited paths are strictly barred from long-term memory."
            )

        sanitized_note = check_res.redacted_content
        topic_clean = req.topic.strip()
        if topic_clean not in self._mock_memory_store:
            self._mock_memory_store[topic_clean] = []
        self._mock_memory_store[topic_clean].append(sanitized_note)

        status_msg = "Sanitized and stored" if check_res.redacted_content != req.note else "Stored"
        return f"{status_msg} fact under topic [{topic_clean}] successfully."
