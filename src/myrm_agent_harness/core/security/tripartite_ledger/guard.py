"""Action Semantics Guard and Zero-Knowledge Ops Controller.

Enforces:
1. Semantic mode isolation (REPLAY_LOG read-only, OFFLINE_EVAL simulation, RE_EXECUTE live).
2. Pre-I/O audit persistence gate (never initiate live external I/O without prior ledger commit).
3. Zero-knowledge operational controls (ops stops task without business content exposure).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

from myrm_agent_harness.core.security.tripartite_ledger.ledger import TripartiteAuditLedger
from myrm_agent_harness.core.security.tripartite_ledger.types import (
    ActionExecutionResult,
    ActionSemanticMode,
    ActionSemanticViolationError,
    OpsTelemetryRecord,
    PreIOAuditAssertionError,
)

READ_ONLY_TOOL_PREFIXES: Final[tuple[str, ...]] = (
    "read_",
    "get_",
    "list_",
    "search_",
    "view_",
    "describe_",
)


class ActionSemanticsGuard:
    """Guards execution by enforcing strict action semantics and pre-I/O audit assertions."""

    def __init__(self, ledger: TripartiteAuditLedger) -> None:
        self._ledger = ledger

    @staticmethod
    def is_read_only_tool(tool_name: str) -> bool:
        """Determine if a tool name represents a read-only operation."""
        lower_name = tool_name.lower()
        return any(lower_name.startswith(prefix) for prefix in READ_ONLY_TOOL_PREFIXES)

    def execute_action(
        self,
        mode: ActionSemanticMode,
        tool_name: str,
        executor: Callable[[], str],
        audit_record_id: str | None = None,
        explicit_confirmed: bool = False,
    ) -> ActionExecutionResult:
        """Execute or intercept action according to its semantic mode."""
        if mode == ActionSemanticMode.REPLAY_LOG:
            raise ActionSemanticViolationError(
                f"REPLAY_LOG mode strictly forbids tool execution and external I/O (tool: {tool_name})"
            )

        if mode == ActionSemanticMode.OFFLINE_EVAL:
            if self.is_read_only_tool(tool_name):
                output = executor()
                return ActionExecutionResult(
                    mode=mode,
                    tool_name=tool_name,
                    executed=True,
                    is_simulated=False,
                    result=output,
                )
            # Side-effect tools are mocked during offline eval
            return ActionExecutionResult(
                mode=mode,
                tool_name=tool_name,
                executed=False,
                is_simulated=True,
                result=f"[MOCK_SIMULATION] Side-effect tool {tool_name} was suppressed in OFFLINE_EVAL mode",
            )

        if mode == ActionSemanticMode.RE_EXECUTE:
            if not explicit_confirmed:
                raise ActionSemanticViolationError(
                    f"RE_EXECUTE mode requires explicit operator confirmation for live effects (tool: {tool_name})"
                )

            # Pre-I/O Audit Gate: Audit record MUST be persisted in ledger beforehand!
            if not audit_record_id or not self._ledger.has_record(audit_record_id):
                raise PreIOAuditAssertionError(
                    f"Live external I/O blocked: Audit record '{audit_record_id}' must be committed "
                    f"to Immutable Audit Ledger prior to execution of tool '{tool_name}'"
                )

            output = executor()
            return ActionExecutionResult(
                mode=mode,
                tool_name=tool_name,
                executed=True,
                is_simulated=False,
                result=output,
                audit_record_id=audit_record_id,
            )

        raise ActionSemanticViolationError(f"Unsupported action semantic mode: {mode}")


class ZeroKnowledgeOpsController:
    """Operational management without payload exposure or business content leakage."""

    def __init__(self) -> None:
        self._tasks: dict[str, dict[str, str | int]] = {}

    def register_task(self, task_id: str, agent_id: str, memory_bytes: int = 1048576) -> None:
        """Register a task with pure operational telemetry (no business payload)."""
        self._tasks[task_id] = {
            "agent_id": agent_id,
            "start_time": int(time.time() * 1000),
            "memory_bytes": memory_bytes,
            "state": "RUNNING",
        }

    def get_telemetry(self, task_id: str) -> OpsTelemetryRecord:
        """Fetch operational telemetry. Strictly contains no prompt/chat/business content."""
        task_data = self._tasks.get(task_id)
        if not task_data:
            return OpsTelemetryRecord(
                task_id=task_id,
                agent_id="unknown",
                runtime_ms=0,
                memory_bytes=0,
                state="NOT_FOUND",
            )

        start_time = int(task_data.get("start_time", 0))
        runtime_ms = int(time.time() * 1000) - start_time
        return OpsTelemetryRecord(
            task_id=task_id,
            agent_id=str(task_data.get("agent_id", "unknown")),
            runtime_ms=max(0, runtime_ms),
            memory_bytes=int(task_data.get("memory_bytes", 0)),
            state=str(task_data.get("state", "RUNNING")),
        )

    def force_stop(self, task_id: str, operator_id: str) -> bool:
        """Force-stop task execution by ops operator without access to task business content."""
        if not operator_id:
            return False
        task_data = self._tasks.get(task_id)
        if not task_data:
            return False

        task_data["state"] = "STOPPED_BY_OPS"
        return True
