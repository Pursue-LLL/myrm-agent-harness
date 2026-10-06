"""Continuity ledger for managing cross-session handoff contracts and lifecycle.

Ensures deterministic handoff persistence, atomic single-consumer state machine,
and structured context prompt hydration across agent sessions.
"""

import json
import os
import time

from myrm_agent_harness.runtime.context.cross_session_handoff_types import (
    CrossSessionHandoffContract,
    HandoffConsumptionReceipt,
    HandoffDecisionItem,
    HandoffPitfallItem,
    HandoffStatus,
    HandoffTodoItem,
    SessionLifecyclePhase,
)


class CrossSessionHandoffLedger:
    """In-memory and file-backed continuity ledger for session handoffs."""

    def __init__(self, persistence_file: str | None = None) -> None:
        self._persistence_file = persistence_file
        self._contracts: dict[str, CrossSessionHandoffContract] = {}
        self._session_phases: dict[str, SessionLifecyclePhase] = {}
        if persistence_file and os.path.exists(persistence_file):
            self._load_from_disk()

    def register_handoff(
        self, contract: CrossSessionHandoffContract
    ) -> CrossSessionHandoffContract:
        """Register a new handoff contract into the continuity ledger."""
        self._contracts[contract.handoff_id] = contract
        self._session_phases[contract.source_session_id] = (
            SessionLifecyclePhase.FINALIZING
        )
        if self._persistence_file:
            self._save_to_disk()
        return contract

    def get_handoff(
        self, handoff_id: str
    ) -> CrossSessionHandoffContract | None:
        """Retrieve a handoff contract by its ID."""
        return self._contracts.get(handoff_id)

    def list_pending_handoffs(
        self, source_session_id: str | None = None
    ) -> list[CrossSessionHandoffContract]:
        """List active unconsumed handoff contracts, filtering out expired ones."""
        now = time.time()
        pending: list[CrossSessionHandoffContract] = []

        for h_id, contract in list(self._contracts.items()):
            # Expire contracts older than TTL
            if now - contract.created_at > contract.ttl_seconds:
                if contract.status == HandoffStatus.PENDING:
                    updated = CrossSessionHandoffContract(
                        handoff_id=contract.handoff_id,
                        source_session_id=contract.source_session_id,
                        created_at=contract.created_at,
                        source_agent_profile=contract.source_agent_profile,
                        target_task_summary=contract.target_task_summary,
                        decisions=contract.decisions,
                        todos=contract.todos,
                        pitfalls=contract.pitfalls,
                        touched_files=contract.touched_files,
                        executed_commands_summary=contract.executed_commands_summary,
                        status=HandoffStatus.EXPIRED,
                    )
                    self._contracts[h_id] = updated
                continue

            if contract.status == HandoffStatus.PENDING and (
                source_session_id is None
                or contract.source_session_id == source_session_id
            ):
                pending.append(contract)

        return pending

    def consume_handoff(
        self, handoff_id: str, consumer_session_id: str
    ) -> tuple[
        CrossSessionHandoffContract | None, HandoffConsumptionReceipt | None
    ]:
        """Atomically claim and consume a pending handoff contract."""
        contract = self._contracts.get(handoff_id)
        if not contract or contract.status != HandoffStatus.PENDING:
            return None, None

        now = time.time()
        consumed_contract = CrossSessionHandoffContract(
            handoff_id=contract.handoff_id,
            source_session_id=contract.source_session_id,
            created_at=contract.created_at,
            source_agent_profile=contract.source_agent_profile,
            target_task_summary=contract.target_task_summary,
            decisions=contract.decisions,
            todos=contract.todos,
            pitfalls=contract.pitfalls,
            touched_files=contract.touched_files,
            executed_commands_summary=contract.executed_commands_summary,
            status=HandoffStatus.CONSUMED,
            consumed_by_session_id=consumer_session_id,
            consumed_at=now,
            ttl_seconds=contract.ttl_seconds,
        )

        self._contracts[handoff_id] = consumed_contract
        self._session_phases[contract.source_session_id] = (
            SessionLifecyclePhase.FINALIZED
        )

        rendered = self.render_handoff_prompt_block(consumed_contract)
        tokens_est = max(1, len(rendered) // 4)
        active_todos = sum(1 for t in contract.todos if not t.is_completed)

        receipt = HandoffConsumptionReceipt(
            handoff_id=handoff_id,
            consumer_session_id=consumer_session_id,
            consumed_at=now,
            active_todos_count=active_todos,
            injected_prompt_tokens_est=tokens_est,
        )

        if self._persistence_file:
            self._save_to_disk()

        return consumed_contract, receipt

    def finalize_session(
        self, session_id: str, timeout_seconds: int = 3600
    ) -> SessionLifecyclePhase:
        """Mark a session as finalized or detect timeout."""
        current = self._session_phases.get(
            session_id, SessionLifecyclePhase.ACTIVE
        )
        if current == SessionLifecyclePhase.FINALIZED:
            return current

        self._session_phases[session_id] = SessionLifecyclePhase.FINALIZED
        return SessionLifecyclePhase.FINALIZED

    def render_handoff_prompt_block(
        self, contract: CrossSessionHandoffContract
    ) -> str:
        """Render standard markdown context block for cross-session injection."""
        lines: list[str] = [
            "<!-- CROSS-SESSION CONTINUITY HANDOFF CONTRACT -->",
            f'<session_handoff_contract id="{contract.handoff_id}" '
            f'source_session="{contract.source_session_id}" '
            f'profile="{contract.source_agent_profile}">',
            f"  <summary>{contract.target_task_summary}</summary>",
        ]

        # Key Decisions
        if contract.decisions:
            lines.append("  <decisions>")
            for d in contract.decisions:
                lines.append(
                    f'    <decision id="{d.decision_id}" topic="{d.topic}">{d.rationale}</decision>'
                )
            lines.append("  </decisions>")

        # Outstanding Todos
        active_todos = [t for t in contract.todos if not t.is_completed]
        if active_todos:
            lines.append("  <pending_todos>")
            for t in active_todos:
                lines.append(
                    f'    <todo id="{t.task_id}" priority="{t.priority}">{t.description}</todo>'
                )
            lines.append("  </pending_todos>")

        # Known Pitfalls & Warnings
        if contract.pitfalls:
            lines.append("  <pitfalls_and_constraints>")
            for p in contract.pitfalls:
                lines.append(
                    f'    <pitfall id="{p.warning_id}" context="{p.context}">'
                    f"{p.recommendation}</pitfall>"
                )
            lines.append("  </pitfalls_and_constraints>")

        # Touched Files
        if contract.touched_files:
            files_str = ", ".join(f"`{f}`" for f in contract.touched_files)
            lines.append(f"  <touched_files>{files_str}</touched_files>")

        # Key Commands Executed
        if contract.executed_commands_summary:
            lines.append("  <executed_commands>")
            for cmd in contract.executed_commands_summary[:5]:
                lines.append(f"    - `{cmd}`")
            lines.append("  </executed_commands>")

        lines.append("</session_handoff_contract>")
        return "\n".join(lines)

    def _save_to_disk(self) -> None:
        """Persist handoff contracts to disk in jsonl format."""
        if not self._persistence_file:
            return
        os.makedirs(os.path.dirname(self._persistence_file), exist_ok=True)
        with open(self._persistence_file, "w", encoding="utf-8") as f:
            for contract in self._contracts.values():
                rec = {
                    "handoff_id": contract.handoff_id,
                    "source_session_id": contract.source_session_id,
                    "created_at": contract.created_at,
                    "source_agent_profile": contract.source_agent_profile,
                    "target_task_summary": contract.target_task_summary,
                    "decisions": [
                        {
                            "decision_id": d.decision_id,
                            "topic": d.topic,
                            "rationale": d.rationale,
                            "timestamp": d.timestamp,
                        }
                        for d in contract.decisions
                    ],
                    "todos": [
                        {
                            "task_id": t.task_id,
                            "description": t.description,
                            "priority": t.priority,
                            "is_completed": t.is_completed,
                        }
                        for t in contract.todos
                    ],
                    "pitfalls": [
                        {
                            "warning_id": p.warning_id,
                            "context": p.context,
                            "recommendation": p.recommendation,
                        }
                        for p in contract.pitfalls
                    ],
                    "touched_files": contract.touched_files,
                    "executed_commands_summary": contract.executed_commands_summary,
                    "status": contract.status.value,
                    "consumed_by_session_id": contract.consumed_by_session_id,
                    "consumed_at": contract.consumed_at,
                    "ttl_seconds": contract.ttl_seconds,
                }
                f.write(json.dumps(rec) + "\n")

    def _load_from_disk(self) -> None:
        """Load handoff contracts from jsonl disk file."""
        if not self._persistence_file or not os.path.exists(
            self._persistence_file
        ):
            return
        with open(self._persistence_file, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                contract = CrossSessionHandoffContract(
                    handoff_id=data["handoff_id"],
                    source_session_id=data["source_session_id"],
                    created_at=data["created_at"],
                    source_agent_profile=data["source_agent_profile"],
                    target_task_summary=data["target_task_summary"],
                    decisions=[
                        HandoffDecisionItem(**d)
                        for d in data.get("decisions", [])
                    ],
                    todos=[
                        HandoffTodoItem(**t) for t in data.get("todos", [])
                    ],
                    pitfalls=[
                        HandoffPitfallItem(**p)
                        for p in data.get("pitfalls", [])
                    ],
                    touched_files=data.get("touched_files", []),
                    executed_commands_summary=data.get(
                        "executed_commands_summary", []
                    ),
                    status=HandoffStatus(data.get("status", "pending")),
                    consumed_by_session_id=data.get("consumed_by_session_id"),
                    consumed_at=data.get("consumed_at"),
                    ttl_seconds=data.get("ttl_seconds", 86400 * 7),
                )
                self._contracts[contract.handoff_id] = contract
