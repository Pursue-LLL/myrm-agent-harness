"""[INPUT]
- myrm_agent_harness.observability.diagnostics.fleet_telemetry::{
    FleetDiagnosisReport,
    FleetNodeState,
    FleetNodeTarget,
    FleetSixStateDiagnoser,
    ProbeStage,
    ProviderErrorCategory,
    classify_provider_error,
}

[OUTPUT]
- test_provider_quota_classification_402_and_credit_exhausted
- test_provider_quota_classification_429_rate_limit
- test_provider_quota_classification_401_invalid_key
- test_diagnoser_physical_offline
- test_diagnoser_credential_misconfigured
- test_diagnoser_gateway_stopped
- test_diagnoser_runner_broken
- test_diagnoser_provider_quota_exhausted
- test_diagnoser_all_pass_online

[POS]
tests/observability/diagnostics/fleet_telemetry/test_fleet_six_state.py — 分布式机队六态诊断与 Provider 额度归因单元测试。
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.observability.diagnostics.fleet_telemetry import (
    FleetNodeState,
    FleetNodeTarget,
    FleetSixStateDiagnoser,
    ProbeStage,
    ProviderErrorCategory,
    classify_provider_error,
)


def test_provider_quota_classification_402_and_credit_exhausted() -> None:
    """402 状态码或包含欠费关键词时，精准归因为 QUOTA_EXHAUSTED。"""
    res1 = classify_provider_error(402, "Payment Required", provider_name="Anthropic")
    assert res1.is_provider_issue is True
    assert res1.category == ProviderErrorCategory.QUOTA_EXHAUSTED
    assert "Anthropic" in res1.root_cause
    assert "充值" in res1.recommended_action

    res2 = classify_provider_error(
        400,
        {"error": {"message": "You exceeded your current quota, please check your plan"}},
        provider_name="OpenAI",
    )
    assert res2.is_provider_issue is True
    assert res2.category == ProviderErrorCategory.QUOTA_EXHAUSTED


def test_provider_quota_classification_429_rate_limit() -> None:
    """429 状态码归因为 RATE_LIMITED，建议配置指数退避或模型分流。"""
    res = classify_provider_error(429, "Too Many Requests", provider_name="DeepSeek")
    assert res.is_provider_issue is True
    assert res.category == ProviderErrorCategory.RATE_LIMITED
    assert "退避" in res.recommended_action or "分流" in res.recommended_action


def test_provider_quota_classification_401_invalid_key() -> None:
    """401 状态码归因为 AUTH_INVALID，提示检查 API Key。"""
    res = classify_provider_error(401, "Invalid API Key", provider_name="Google")
    assert res.is_provider_issue is True
    assert res.category == ProviderErrorCategory.AUTH_INVALID
    assert "密钥" in res.root_cause or "Key" in res.root_cause


@pytest.mark.asyncio
async def test_diagnoser_physical_offline() -> None:
    """物理网络不通时，判定为 OFFLINE 并快速中断后续探针。"""

    async def mock_physical(_h: str, _p: int) -> tuple[bool, str]:
        return False, "Connection refused / Host unreachable"

    diagnoser = FleetSixStateDiagnoser(physical_probe=mock_physical)
    target = FleetNodeTarget(node_id="n1", node_name="Worker-Mac-1", host="192.168.1.100")

    report = await diagnoser.diagnose(target)
    assert report.state == FleetNodeState.OFFLINE
    assert len(report.stages) == 1
    assert report.stages[0].stage == ProbeStage.PHYSICAL_NETWORK
    assert report.stages[0].passed is False
    assert "电源" in report.recommended_action or "网络" in report.recommended_action


@pytest.mark.asyncio
async def test_diagnoser_credential_misconfigured() -> None:
    """网络通但鉴权失败，判定为 MISCONFIGURED。"""

    async def mock_physical(_h: str, _p: int) -> tuple[bool, str]:
        return True, "OK"

    async def mock_cred(_t: FleetNodeTarget) -> tuple[bool, str]:
        return False, "Bearer Token expired"

    diagnoser = FleetSixStateDiagnoser(
        physical_probe=mock_physical,
        credential_probe=mock_cred,
    )
    target = FleetNodeTarget(node_id="n2", node_name="Worker-GPU-1", host="10.0.0.2")

    report = await diagnoser.diagnose(target)
    assert report.state == FleetNodeState.MISCONFIGURED
    assert len(report.stages) == 2
    assert report.stages[1].stage == ProbeStage.CREDENTIAL_AUTH
    assert report.stages[1].passed is False


@pytest.mark.asyncio
async def test_diagnoser_gateway_stopped() -> None:
    """网络通但网关守护进程未启动，判定为 GATEWAY_STOPPED。"""

    async def mock_physical(_h: str, _p: int) -> tuple[bool, str]:
        return True, "OK"

    async def mock_cred(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_gw(_t: FleetNodeTarget) -> tuple[bool, str]:
        return False, "HTTP 502 Bad Gateway / Connection reset"

    diagnoser = FleetSixStateDiagnoser(
        physical_probe=mock_physical,
        credential_probe=mock_cred,
        gateway_probe=mock_gw,
    )
    target = FleetNodeTarget(node_id="n3", node_name="Worker-Mac-2", host="10.0.0.3")

    report = await diagnoser.diagnose(target)
    assert report.state == FleetNodeState.GATEWAY_STOPPED
    assert "./myrm start" in report.recommended_action


@pytest.mark.asyncio
async def test_diagnoser_runner_broken() -> None:
    """网关正常但沙箱执行器崩溃，判定为 RUNNER_BROKEN。"""

    async def mock_physical(_h: str, _p: int) -> tuple[bool, str]:
        return True, "OK"

    async def mock_gw(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_runner(_t: FleetNodeTarget) -> tuple[bool, str]:
        return False, "Docker daemon socket not found"

    diagnoser = FleetSixStateDiagnoser(
        physical_probe=mock_physical,
        gateway_probe=mock_gw,
        runner_probe=mock_runner,
    )
    target = FleetNodeTarget(node_id="n4", node_name="Worker-Linux-1", host="10.0.0.4")

    report = await diagnoser.diagnose(target)
    assert report.state == FleetNodeState.RUNNER_BROKEN
    assert "沙箱" in report.root_cause or "Docker" in report.recommended_action


@pytest.mark.asyncio
async def test_diagnoser_provider_quota_exhausted() -> None:
    """网络、网关、沙箱均正常，但模型 API 欠费，精准判定为 PROVIDER_UNAVAILABLE。"""

    async def mock_physical(_h: str, _p: int) -> tuple[bool, str]:
        return True, "OK"

    async def mock_gw(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_runner(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_prov(_t: FleetNodeTarget) -> tuple[int, str]:
        return 402, "credit_balance_too_low: Your organization credit balance is too low"

    diagnoser = FleetSixStateDiagnoser(
        physical_probe=mock_physical,
        gateway_probe=mock_gw,
        runner_probe=mock_runner,
        provider_probe=mock_prov,
    )
    target = FleetNodeTarget(
        node_id="n5",
        node_name="Mac-Studio-Tony",
        host="10.0.0.5",
        provider_name="Anthropic",
        model_name="claude-3-5-sonnet",
    )

    report = await diagnoser.diagnose(target)
    assert report.state == FleetNodeState.PROVIDER_UNAVAILABLE
    assert "余额已耗尽或欠费停服" in report.root_cause
    assert "充值" in report.recommended_action


@pytest.mark.asyncio
async def test_diagnoser_all_pass_online() -> None:
    """全部 5 阶段探针通过，报告 ONLINE。"""

    async def mock_physical(_h: str, _p: int) -> tuple[bool, str]:
        return True, "OK"

    async def mock_cred(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_gw(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_runner(_t: FleetNodeTarget) -> tuple[bool, str]:
        return True, "OK"

    async def mock_prov(_t: FleetNodeTarget) -> tuple[int, str]:
        return 200, "OK"

    diagnoser = FleetSixStateDiagnoser(
        physical_probe=mock_physical,
        credential_probe=mock_cred,
        gateway_probe=mock_gw,
        runner_probe=mock_runner,
        provider_probe=mock_prov,
    )
    target = FleetNodeTarget(node_id="n6", node_name="Prod-Cluster-1", host="10.0.0.6")

    report = await diagnoser.diagnose(target)
    assert report.state == FleetNodeState.ONLINE
    assert len(report.stages) == 5
    assert all(s.passed for s in report.stages)
    assert "良好" in report.recommended_action
