"""[INPUT] NamedSubagentInstanceConfig, SubagentReportItem, and SettlementNoticeItem.
[OUTPUT] SubagentReportWakeupCoordinator orchestrating multi-instance configs, delivery wakeup, and FIFO settlement.
[POS] Coordinator component implementing next-step steer parent wakeup and unattended permission governance.
"""

from __future__ import annotations

import logging

from .queue import OrderedSettlementFifoQueue
from .types import (
    NamedSubagentInstanceConfig,
    OrderedFifoQueueEnvelope,
    PermissionMode,
    ReportDeliveryMode,
    SettlementNoticeItem,
    SubagentReportItem,
)

logger = logging.getLogger(__name__)


class SubagentReportWakeupCoordinator:
    """Coordinator governing subagent active report wakeup, FIFO ordering, and unattended execution."""

    def __init__(self, queue: OrderedSettlementFifoQueue | None = None) -> None:
        self.queue = queue or OrderedSettlementFifoQueue()
        self._instances: dict[str, NamedSubagentInstanceConfig] = {}

    def register_instance(self, config: NamedSubagentInstanceConfig) -> None:
        """Register or update a named subagent instance configuration."""
        self._instances[config.instance_name] = config
        logger.info(
            "Registered named subagent instance %s (role=%s, permission_mode=%s)",
            config.instance_name,
            config.role,
            config.permission_mode.value,
        )

    def get_instance(self, instance_name: str) -> NamedSubagentInstanceConfig | None:
        """Fetch instance config by name."""
        return self._instances.get(instance_name)

    def list_instances(self) -> list[NamedSubagentInstanceConfig]:
        """List all configured named subagents."""
        return list(self._instances.values())

    def submit_report(
        self,
        instance_name: str,
        task_id: str,
        summary: str,
        content: str = "",
        delivery_mode: ReportDeliveryMode | None = None,
        severity: str = "normal",
        metadata: dict[str, str] | None = None,
    ) -> OrderedFifoQueueEnvelope:
        """Submit an active progress report from a named subagent.

        If delivery_mode is NEXT_STEP, flags envelope to steer and wake parent at the next step boundary.
        If severity is 'critical', overrides delivery to prioritize urgent parent interruption.
        """
        instance_cfg = self.get_instance(instance_name)
        effective_mode = delivery_mode or (
            instance_cfg.report_delivery if instance_cfg else ReportDeliveryMode.NEXT_STEP
        )

        wakes_parent = (effective_mode == ReportDeliveryMode.NEXT_STEP)

        report = SubagentReportItem(
            subagent_id=instance_name,
            task_id=task_id,
            summary=summary,
            content=content,
            delivery_mode=effective_mode,
            severity=severity,
            metadata=metadata or {},
        )

        return self.queue.enqueue_report(report=report, wakes_parent=wakes_parent)

    def submit_settlement(
        self,
        instance_name: str,
        task_id: str,
        exit_code: int = 0,
        status: str = "completed",
        summary: str = "",
    ) -> OrderedFifoQueueEnvelope:
        """Submit an automated settlement notice, guaranteed to be processed after reports."""
        settlement = SettlementNoticeItem(
            subagent_id=instance_name,
            task_id=task_id,
            exit_code=exit_code,
            status=status,
            summary=summary or f"Subagent {instance_name} terminated with exit code {exit_code}",
        )
        return self.queue.enqueue_settlement(settlement=settlement)

    def drain_step_batch(self, max_items: int = 50) -> list[OrderedFifoQueueEnvelope]:
        """Drain events at the parent agent step boundary in strict FIFO order."""
        return self.queue.drain_batch(max_items=max_items)

    def should_wake_parent(self, envelope: OrderedFifoQueueEnvelope) -> bool:
        """Evaluate whether a queued envelope requires waking a parked parent agent."""
        return envelope.wakes_parent

    def check_unattended_permission(
        self,
        instance_name: str,
        tool_name: str,
    ) -> bool:
        """Evaluate unattended execution authorization according to permissionMode.

        - NEVER: Always rejects automated bypass, requiring human-in-the-loop.
        - APPROVE_FOR_ME: Permits tool if in instance's tools_allowed whitelist.
        - DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX: Bypasses all approval gates.
        """
        instance = self.get_instance(instance_name)
        if not instance:
            logger.warning("Unregistered instance %s attempted unattended execution", instance_name)
            return False

        if instance.permission_mode == PermissionMode.NEVER:
            return False

        if instance.permission_mode == PermissionMode.DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX:
            return True

        if instance.permission_mode == PermissionMode.APPROVE_FOR_ME:
            return "*" in instance.tools_allowed or tool_name in instance.tools_allowed

        return False
