"""Dev Sandbox Fence Engine integrating SQL write blocking, synthetic data, and branch gates."""

from __future__ import annotations

import logging
import threading
import uuid

from .branch_and_directory_gate import BranchAndDirectoryGate
from .sql_write_interceptor import SqlWriteOperationInterceptor
from .synthetic_data_fence import SyntheticDataFence
from .types import (
    DevExecutionMode,
    DevOperationInspection,
    DevSandboxPolicy,
    DevViolationAlert,
    FenceInspectionResult,
    ViolationType,
)

logger = logging.getLogger(__name__)


class DevSandboxFenceEngine:
    """Core enforcement engine ensuring development agents have zero production write privileges."""

    def __init__(
        self,
        policy: DevSandboxPolicy | None = None,
        mode: DevExecutionMode = DevExecutionMode.DEV_ISOLATED,
        sql_interceptor: SqlWriteOperationInterceptor | None = None,
        synthetic_fence: SyntheticDataFence | None = None,
        branch_gate: BranchAndDirectoryGate | None = None,
    ) -> None:
        self.policy = policy or DevSandboxPolicy()
        self.mode = mode
        self.sql_interceptor = sql_interceptor or SqlWriteOperationInterceptor()
        self.synthetic_fence = synthetic_fence or SyntheticDataFence()
        self.branch_gate = branch_gate or BranchAndDirectoryGate()
        self._lock = threading.Lock()
        self._alerts: list[DevViolationAlert] = []

    def inspect_operation(
        self, op: DevOperationInspection
    ) -> FenceInspectionResult:
        """Inspect and enforce dev sandbox restrictions on a submitted operation."""
        # If running in production controlled mode, bypass dev sandbox restrictions
        if self.mode == DevExecutionMode.PRODUCTION_CONTROLLED:
            return FenceInspectionResult(
                allowed=True,
                violation_type=None,
                reason="Production controlled mode active; dev sandbox fence bypassed",
                substituted_target=op.target,
            )

        op_type = op.operation_type.lower().strip()
        result: FenceInspectionResult

        if op_type == "sql":
            query = op.payload if op.payload else op.target
            result = self.sql_interceptor.inspect_sql(query)
        elif op_type == "git_branch":
            result = self.branch_gate.inspect_git_branch(op.target, self.policy)
        elif op_type in ("file_write", "file_mutation"):
            result = self.branch_gate.inspect_file_write(op.target, self.policy)
        elif op_type in ("db_connect", "database_connection"):
            result = self.synthetic_fence.inspect_db_connection(
                op.target, self.policy.enforce_synthetic_data
            )
        else:
            result = FenceInspectionResult(
                allowed=True,
                violation_type=None,
                reason=f"Operation type '{op.operation_type}' not monitored by dev fence",
                substituted_target=op.target,
            )

        # Record violation alert if operation was blocked or substituted
        if not result.allowed or result.violation_type is not None:
            v_type = result.violation_type or ViolationType.PROD_DB_WRITE_BLOCKED
            alert = DevViolationAlert(
                alert_id=f"alert-{uuid.uuid4().hex[:12]}",
                session_id=op.session_id,
                operation_type=op.operation_type,
                violation_type=v_type,
                reason=result.reason,
                target=op.target,
            )
            with self._lock:
                self._alerts.append(alert)
            logger.warning(
                "Dev sandbox violation detected: [%s] %s (Target: %s)",
                alert.violation_type,
                alert.reason,
                alert.target,
            )

        return result

    def get_alerts(
        self, session_id: str | None = None
    ) -> list[DevViolationAlert]:
        """Retrieve security violation alerts, optionally filtered by session ID."""
        with self._lock:
            if session_id:
                return [a for a in self._alerts if a.session_id == session_id]
            return list(self._alerts)

    def clear_alerts(self) -> None:
        """Clear all logged violation alerts."""
        with self._lock:
            self._alerts.clear()
