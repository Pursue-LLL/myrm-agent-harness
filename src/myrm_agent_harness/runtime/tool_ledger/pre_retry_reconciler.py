"""Pre-retry action audit reconciler and card renderer.

Benchmarked against Mobie CC 0.3.7, durable-pi, and user safety audit invariants:
- Audits planned tool actions before re-executing an interrupted turn.
- Automatically reuses completed results from durable storage to prevent token double-spend.
- Identifies in-flight operations with external side effects and marks them as UNKNOWN,
  requiring explicit user confirmation before any retry attempt.
- Generates markdown cards and JSON payloads for frontend UI rendering.

[OUTPUT]
- PreRetryReconciler: Core auditor coordinating durable tool ledger reconciliation.

[INPUT]
- __future__
- json

[OUTPUT]
- PreRetryReconciler

[POS]
Pre-retry action audit reconciler and card renderer.
"""

from __future__ import annotations

import json

from myrm_agent_harness.runtime.tool_ledger.durable_tool_ledger import DurableToolLedger
from myrm_agent_harness.runtime.tool_ledger.ledger_types import (
    ActionReconciliationItem,
    PreRetryReconciliationReport,
    ReconciliationActionStatus,
    ToolExecutionStatus,
)


class PreRetryReconciler:
    """Audits planned tool invocations against durable ledger before dispatching a retry."""

    def __init__(self, ledger: DurableToolLedger) -> None:
        self._ledger = ledger

    def audit_planned_actions(
        self,
        session_id: str,
        task_id: str,
        planned_actions: list[tuple[str, str, str, bool]]
        | tuple[tuple[str, str, str, bool], ...],
    ) -> PreRetryReconciliationReport:
        """Audit a list of planned actions against the durable execution ledger.

        Args:
            session_id: Target session identifier.
            task_id: Active task identifier.
            planned_actions: Sequence of (call_id, tool_name, arguments_json, is_external_side_effect).
        """
        items: list[ActionReconciliationItem] = []

        for call_id, tool_name, args_json, is_side_effect in planned_actions:
            entry = self._ledger.get_entry(call_id)

            if entry is None:
                # Never attempted prior to interruption
                items.append(
                    ActionReconciliationItem(
                        call_id=call_id,
                        tool_name=tool_name,
                        arguments_json=args_json,
                        reconciliation_status=ReconciliationActionStatus.PENDING_EXECUTION,
                        can_auto_resume=True,
                        user_guidance="未执行，恢复时可正常调度执行",
                    )
                )
            elif entry.status == ToolExecutionStatus.SUCCEEDED:
                # Successfully completed and artifact captured
                items.append(
                    ActionReconciliationItem(
                        call_id=call_id,
                        tool_name=tool_name,
                        arguments_json=args_json,
                        reconciliation_status=ReconciliationActionStatus.REUSABLE_COMPLETED,
                        can_auto_resume=True,
                        user_guidance="已执行成功，结果已持久化，自动复用（节省 Token 与时间）",
                    )
                )
            elif entry.status == ToolExecutionStatus.FAILED:
                # Explicit failure
                items.append(
                    ActionReconciliationItem(
                        call_id=call_id,
                        tool_name=tool_name,
                        arguments_json=args_json,
                        reconciliation_status=ReconciliationActionStatus.FAILED_NEEDS_RETRY,
                        can_auto_resume=True,
                        user_guidance="上次执行失败，恢复时将发起重试",
                    )
                )
            elif (
                entry.status in (ToolExecutionStatus.UNKNOWN, ToolExecutionStatus.STARTED)
            ):
                if is_side_effect or entry.is_external_side_effect:
                    # External mutation was in-flight when disconnected; high-risk duplicate execution
                    items.append(
                        ActionReconciliationItem(
                            call_id=call_id,
                            tool_name=tool_name,
                            arguments_json=args_json,
                            reconciliation_status=ReconciliationActionStatus.UNKNOWN_REQUIRES_CONFIRMATION,
                            can_auto_resume=False,
                            user_guidance="⚠️ 外部有状态操作在中断时处于未决状态；为防止双写副作用，需人工核对确认后再继续",
                        )
                    )
                else:
                    # Idempotent read operation interrupted; safe to re-execute
                    items.append(
                        ActionReconciliationItem(
                            call_id=call_id,
                            tool_name=tool_name,
                            arguments_json=args_json,
                            reconciliation_status=ReconciliationActionStatus.FAILED_NEEDS_RETRY,
                            can_auto_resume=True,
                            user_guidance="读取操作中断，无外部副作用，可安全重新执行",
                        )
                    )

        return PreRetryReconciliationReport.assemble(
            session_id=session_id, task_id=task_id, items=items
        )

    def render_markdown_card(self, report: PreRetryReconciliationReport) -> str:
        """Render a GitHub Flavored Markdown card summarizing pre-retry reconciliation status."""
        lines: list[str] = [
            "### 🔄 断线重试工具对账审计卡片",
            f"- **会话 ID**: `{report.session_id}`",
            f"- **任务 ID**: `{report.task_id}`",
            f"- **复用成功动作**: `{report.completed_reused_count}`",
            f"- **待执行动作**: `{report.pending_count}`",
            f"- **未决高危动作**: `{report.unknown_danger_count}`",
            f"- **允许自动恢复**: `{'✅ 允许' if report.safe_to_auto_resume else '❌ 需人工确认'}`",
            "",
        ]

        if not report.safe_to_auto_resume:
            lines.extend(
                [
                    "> [!CAUTION]",
                    "> 检测到存在外部副作用且状态未决的工具调用！为防止重复写操作（双花/重复扣费/重复提交），系统已阻断一键自动重发，请人工确认操作结果。",
                    "",
                ]
            )

        lines.extend(
            [
                "| 工具调用 ID | 工具名称 | 对账分类 | 恢复指引 |",
                "| :--- | :--- | :--- | :--- |",
            ]
        )

        for item in report.items:
            status_badge = {
                ReconciliationActionStatus.REUSABLE_COMPLETED: "🟢 已复用",
                ReconciliationActionStatus.PENDING_EXECUTION: "⚪ 待执行",
                ReconciliationActionStatus.UNKNOWN_REQUIRES_CONFIRMATION: "🔴 需确认",
                ReconciliationActionStatus.FAILED_NEEDS_RETRY: "🟡 待重试",
            }.get(item.reconciliation_status, item.reconciliation_status.value)

            lines.append(
                f"| `{item.call_id}` | `{item.tool_name}` | {status_badge} | {item.user_guidance} |"
            )

        return "\n".join(lines)

    def render_json_summary(
        self, report: PreRetryReconciliationReport
    ) -> dict[str, object]:
        """Produce a typed JSON dictionary suitable for frontend rendering."""
        return {
            "session_id": report.session_id,
            "task_id": report.task_id,
            "safe_to_auto_resume": report.safe_to_auto_resume,
            "completed_reused_count": report.completed_reused_count,
            "pending_count": report.pending_count,
            "unknown_danger_count": report.unknown_danger_count,
            "failed_count": report.failed_count,
            "items": [
                {
                    "call_id": i.call_id,
                    "tool_name": i.tool_name,
                    "arguments": json.loads(i.arguments_json)
                    if i.arguments_json.startswith("{")
                    else i.arguments_json,
                    "status": i.reconciliation_status.value,
                    "can_auto_resume": i.can_auto_resume,
                    "guidance": i.user_guidance,
                }
                for i in report.items
            ],
            "timestamp": report.timestamp,
        }
