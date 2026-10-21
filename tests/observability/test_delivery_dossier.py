"""
[INPUT]:
- myrm_agent_harness.observability.delivery_dossier::DeliveryDossierRecorder
- myrm_agent_harness.observability.delivery_dossier::AssetFrictionCalculator
- myrm_agent_harness.observability.delivery_dossier::models

[OUTPUT]:
- Pytest unit tests verifying immutable dossier creation, SHA256 integrity checksums, and stratified asset friction metrics.

[POS]:
tests/observability/test_delivery_dossier.py — 跨智能体交付证据卷宗与资产摩擦可观测性单元测试。
"""

import json
import pytest

from myrm_agent_harness.observability.delivery_dossier import (
    AgentPersonaFingerprint,
    AssetFrictionCalculator,
    AssetHealthTag,
    DeliveryDossierRecorder,
    ExecutionMode,
    PhysicalVerificationReceipt,
    TaskSpecRecord,
    ToolExecutionTraceItem,
    UserAcceptanceStatus,
)


def test_delivery_dossier_creation_and_integrity_checksum() -> None:
    recorder = DeliveryDossierRecorder()

    spec = TaskSpecRecord(
        task_goal="实现高可用 Redis 分布式锁",
        acceptance_criteria=["支持自愈热重启", "单测覆盖率 > 90%"],
        non_goals=["不支持单机嵌入式持久化"],
    )
    persona = AgentPersonaFingerprint(
        agent_id="agent-arch-01",
        model_name="claude-3-5-sonnet",
        prompt_hash="ph_abc12345678",
        mounted_skills=["bash", "python_test_runner"],
    )
    tool_traces = [
        ToolExecutionTraceItem(
            tool_name="bash",
            arguments_summary="pytest tests/test_lock.py",
            duration_ms=450.0,
            exit_code=0,
            error_message=None,
        )
    ]
    verification = PhysicalVerificationReceipt(
        test_suite_exit_code=0,
        passed_tests_count=5,
        failed_tests_count=0,
        artifact_path="/workspace/src/lock.py",
        artifact_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        verified_at="2026-10-12T14:00:00Z",
    )

    dossier = recorder.create_dossier(
        task_id="task-lock-99",
        execution_mode=ExecutionMode.MULTI_TURN_AGENT,
        spec=spec,
        persona=persona,
        tool_traces=tool_traces,
        verification=verification,
        acceptance=UserAcceptanceStatus.ACCEPTED,
        total_tokens_consumed=12_000,
        wasted_friction_tokens=300,
        rework_count=0,
    )

    assert dossier.dossier_id.startswith("dos_")
    assert len(dossier.dossier_checksum_sha256) == 64
    assert dossier.acceptance == UserAcceptanceStatus.ACCEPTED

    # 验证按 ID 与 Task 检索
    fetched = recorder.get_dossier(dossier.dossier_id)
    assert fetched is not None
    assert fetched.task_id == "task-lock-99"

    by_task = recorder.get_dossier_by_task("task-lock-99")
    assert by_task is not None
    assert by_task.dossier_id == dossier.dossier_id

    # 验证导出 JSON
    json_str = recorder.export_json(dossier.dossier_id)
    assert json_str is not None
    data = json.loads(json_str)
    assert data["dossier_id"] == dossier.dossier_id
    assert data["verification"]["test_suite_exit_code"] == 0
    assert data["spec"]["task_goal"] == "实现高可用 Redis 分布式锁"


def test_asset_friction_calculator_stratified_evaluation() -> None:
    calculator = AssetFrictionCalculator(min_samples_threshold=3)

    # 1. 样本量不足门槛测试
    res_insufficient = calculator.evaluate_asset(
        skill_id="docker_deploy",
        model_name="deepseek-chat",
        execution_mode=ExecutionMode.MULTI_TURN_AGENT,
    )
    assert res_insufficient.health_tag == AssetHealthTag.SAMPLE_INSUFFICIENT
    assert res_insufficient.sample_count == 0

    # 2. 注入 3 次高采纳、零返工的优良样本 (用于 sonnet)
    for _ in range(3):
        calculator.record_trial(
            skill_id="docker_deploy",
            model_name="claude-3-5-sonnet",
            execution_mode=ExecutionMode.MULTI_TURN_AGENT,
            accepted=True,
            retries=0,
            rework=False,
            wasted_tokens=50,
            baseline_tokens=5000,
        )

    sonnet_metric = calculator.evaluate_asset(
        skill_id="docker_deploy",
        model_name="claude-3-5-sonnet",
        execution_mode=ExecutionMode.MULTI_TURN_AGENT,
    )
    assert sonnet_metric.health_tag == AssetHealthTag.CORE_EFFICIENT
    assert sonnet_metric.true_efficacy_rate_pct == 100.0
    assert sonnet_metric.friction_index <= 0.25
    assert "核心高效资产" in sonnet_metric.governance_advice

    # 3. 针对不同模型 deepseek 注入高重试、高返工的劣质样本
    for _ in range(3):
        calculator.record_trial(
            skill_id="docker_deploy",
            model_name="deepseek-chat",
            execution_mode=ExecutionMode.MULTI_TURN_AGENT,
            accepted=False,
            retries=4,
            rework=True,
            wasted_tokens=4000,
            baseline_tokens=5000,
        )

    deepseek_metric = calculator.evaluate_asset(
        skill_id="docker_deploy",
        model_name="deepseek-chat",
        execution_mode=ExecutionMode.MULTI_TURN_AGENT,
    )
    assert deepseek_metric.health_tag == AssetHealthTag.FRICTION_ASSASSIN
    assert deepseek_metric.true_efficacy_rate_pct == 0.0
    assert deepseek_metric.friction_index >= 0.60
    assert "摩擦刺客资产" in deepseek_metric.governance_advice

    # 4. 验证分桶隔离性：sonnet 的指标依然是 CORE_EFFICIENT
    sonnet_check = calculator.evaluate_asset(
        skill_id="docker_deploy",
        model_name="claude-3-5-sonnet",
        execution_mode=ExecutionMode.MULTI_TURN_AGENT,
    )
    assert sonnet_check.health_tag == AssetHealthTag.CORE_EFFICIENT
