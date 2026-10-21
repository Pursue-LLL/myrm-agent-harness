"""[INPUT] Harness report_fifo submodule exports.
[OUTPUT] Unit tests verifying subagent report delivery wakeup, Report-before-Settlement FIFO ordering, and unattended permission modes.
[POS] Unit tests for SubagentReportWakeupCoordinator and OrderedSettlementFifoQueue.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.sub_agents.report_fifo import (
    FifoItemType,
    NamedSubagentInstanceConfig,
    OrderedSettlementFifoQueue,
    PermissionMode,
    ReportDeliveryMode,
    SubagentReportWakeupCoordinator,
)


@pytest.fixture
def coordinator() -> SubagentReportWakeupCoordinator:
    queue = OrderedSettlementFifoQueue()
    return SubagentReportWakeupCoordinator(queue=queue)


@pytest.fixture
def sample_instances() -> list[NamedSubagentInstanceConfig]:
    return [
        NamedSubagentInstanceConfig(
            instance_name="codex-worker-01",
            role="code_implementer",
            model_name="deepseek-coder",
            permission_mode=PermissionMode.APPROVE_FOR_ME,
            report_delivery=ReportDeliveryMode.NEXT_STEP,
            tools_allowed=["tool_git_commit", "tool_pytest"],
        ),
        NamedSubagentInstanceConfig(
            instance_name="researcher-strict",
            role="doc_researcher",
            model_name="claude-3-5-sonnet",
            permission_mode=PermissionMode.NEVER,
            report_delivery=ReportDeliveryMode.QUIET,
            tools_allowed=[],
        ),
        NamedSubagentInstanceConfig(
            instance_name="sandbox-ci-bot",
            role="ci_runner",
            model_name="gpt-4o-mini",
            permission_mode=PermissionMode.DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX,
            report_delivery=ReportDeliveryMode.NEXT_STEP,
            tools_allowed=["*"],
        ),
    ]


def test_named_instance_unattended_permissions(
    coordinator: SubagentReportWakeupCoordinator,
    sample_instances: list[NamedSubagentInstanceConfig],
) -> None:
    for inst in sample_instances:
        coordinator.register_instance(inst)

    assert coordinator.get_instance("codex-worker-01") is not None
    assert len(coordinator.list_instances()) == 3

    # 1. APPROVE_FOR_ME: allowed only for whitelisted tools
    assert coordinator.check_unattended_permission("codex-worker-01", "tool_pytest") is True
    assert coordinator.check_unattended_permission("codex-worker-01", "tool_drop_db") is False

    # 2. NEVER: rejected regardless of tool
    assert coordinator.check_unattended_permission("researcher-strict", "tool_pytest") is False
    assert coordinator.check_unattended_permission("researcher-strict", "read_file") is False

    # 3. DANGEROUSLY_BYPASS_APPROVALS_AND_SANDBOX: always allowed
    assert coordinator.check_unattended_permission("sandbox-ci-bot", "tool_pytest") is True
    assert coordinator.check_unattended_permission("sandbox-ci-bot", "any_dangerous_tool") is True


def test_report_delivery_wakeup_flags(
    coordinator: SubagentReportWakeupCoordinator,
    sample_instances: list[NamedSubagentInstanceConfig],
) -> None:
    for inst in sample_instances:
        coordinator.register_instance(inst)

    # 1. codex-worker-01 default NEXT_STEP -> wakes_parent is True
    env_next = coordinator.submit_report(
        instance_name="codex-worker-01",
        task_id="task_build_1",
        summary="Compiled 5 modules successfully",
    )
    assert env_next.wakes_parent is True
    assert env_next.item_type == FifoItemType.REPORT

    # 2. researcher-strict default QUIET -> wakes_parent is False
    env_quiet = coordinator.submit_report(
        instance_name="researcher-strict",
        task_id="task_search_1",
        summary="Found 3 citations",
    )
    assert env_quiet.wakes_parent is False


def test_report_before_settlement_fifo_ordering(
    coordinator: SubagentReportWakeupCoordinator,
) -> None:
    task_id = "task_conflict_race_2600"

    # Simulate race condition: settlement is produced right before a delayed report
    coordinator.submit_settlement(
        instance_name="worker_alpha",
        task_id=task_id,
        exit_code=0,
        status="completed",
        summary="Task completed notice",
    )

    # Subagent submitted an active report for the same task
    coordinator.submit_report(
        instance_name="worker_alpha",
        task_id=task_id,
        summary="Crucial final findings and patch diff",
        content="diff --git a/foo.py ...",
    )

    # When draining, Report MUST strictly precede Settlement for that task
    batch = coordinator.drain_step_batch()
    assert len(batch) == 2

    first_item = batch[0]
    second_item = batch[1]

    assert first_item.item_type == FifoItemType.REPORT
    assert first_item.report_payload is not None
    assert first_item.report_payload.summary == "Crucial final findings and patch diff"

    assert second_item.item_type == FifoItemType.SETTLEMENT
    assert second_item.settlement_payload is not None
    assert second_item.settlement_payload.status == "completed"


def test_drain_step_batch(
    coordinator: SubagentReportWakeupCoordinator,
) -> None:
    coordinator.submit_report(
        instance_name="worker_1",
        task_id="task_1",
        summary="step 1 done",
    )
    coordinator.submit_report(
        instance_name="worker_2",
        task_id="task_2",
        summary="step 2 done",
    )

    assert coordinator.queue.pending_count() == 2
    batch = coordinator.drain_step_batch(max_items=1)
    assert len(batch) == 1
    assert coordinator.queue.pending_count() == 1

    remaining = coordinator.drain_step_batch(max_items=10)
    assert len(remaining) == 1
    assert coordinator.queue.pending_count() == 0


def test_critical_severity_urgent_interrupt(
    coordinator: SubagentReportWakeupCoordinator,
) -> None:
    # 1. Enqueue two normal reports
    coordinator.submit_report(
        instance_name="worker_1",
        task_id="task_1",
        summary="normal step 1",
        severity="normal",
    )
    coordinator.submit_report(
        instance_name="worker_2",
        task_id="task_2",
        summary="normal step 2",
        severity="normal",
    )

    # 2. Enqueue a critical report
    crit_env = coordinator.submit_report(
        instance_name="worker_fatal",
        task_id="task_critical_429",
        summary="Rate limit 429 quota exhausted",
        severity="critical",
    )
    assert crit_env.urgent_interrupt is True
    assert crit_env.wakes_parent is True

    # 3. Drain and verify the critical report was prepended to head of FIFO queue
    batch = coordinator.drain_step_batch()
    assert len(batch) == 3
    assert batch[0].task_id == "task_critical_429"
    assert batch[0].urgent_interrupt is True
    assert batch[1].task_id == "task_1"
    assert batch[2].task_id == "task_2"


def test_summary_rollup_generation(
    coordinator: SubagentReportWakeupCoordinator,
) -> None:
    # 1. Empty queue returns default notice
    assert OrderedSettlementFifoQueue.generate_summary_rollup([]) == "No subagent activity in this step."

    # 2. Add normal report, critical report, and settlement notice
    coordinator.submit_report(
        instance_name="coder",
        task_id="task_1",
        summary="Refactored module A",
        severity="normal",
    )
    coordinator.submit_report(
        instance_name="reviewer",
        task_id="task_2",
        summary="Found critical CVE vulnerability",
        severity="critical",
    )
    coordinator.submit_settlement(
        instance_name="coder",
        task_id="task_1",
        exit_code=0,
        status="completed",
    )

    batch = coordinator.drain_step_batch()
    rollup = OrderedSettlementFifoQueue.generate_summary_rollup(batch)

    assert "[CRITICAL] Report: Found critical CVE vulnerability" in rollup
    assert "Report: Refactored module A" in rollup
    assert "Settlement: completed (exit 0)" in rollup

