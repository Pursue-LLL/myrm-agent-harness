"""[INPUT]
- asyncio, time, typing (Standard library concurrency & timing)
- myrm_agent_harness.observability.diagnostics.fleet_telemetry.models::{FleetDiagnosisReport, FleetNodeState, FleetNodeTarget, ProbeStage, ProbeStageResult}
- myrm_agent_harness.observability.diagnostics.fleet_telemetry.provider_quota::{classify_provider_error, ProviderErrorCategory}

[OUTPUT]
- FleetSixStateDiagnoser: 分布式机队节点五级自省诊断引擎

[POS]
myrm_agent_harness.observability.diagnostics.fleet_telemetry.evaluator — 执行机队六态精细化诊断，精准区分网络断开、网关停止与模型欠费。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from myrm_agent_harness.observability.diagnostics.fleet_telemetry.models import (
    FleetDiagnosisReport,
    FleetNodeState,
    FleetNodeTarget,
    ProbeStage,
    ProbeStageResult,
)
from myrm_agent_harness.observability.diagnostics.fleet_telemetry.provider_quota import (
    classify_provider_error,
)

logger = logging.getLogger(__name__)

# 探针回调签名
PhysicalProbeFn = Callable[[str, int], Awaitable[tuple[bool, str]]]
CredentialProbeFn = Callable[[FleetNodeTarget], Awaitable[tuple[bool, str]]]
GatewayProbeFn = Callable[[FleetNodeTarget], Awaitable[tuple[bool, str]]]
RunnerProbeFn = Callable[[FleetNodeTarget], Awaitable[tuple[bool, str]]]
ProviderProbeFn = Callable[[FleetNodeTarget], Awaitable[tuple[int, str | dict[str, object] | None]]]


async def default_physical_probe(host: str, port: int) -> tuple[bool, str]:
    """默认物理网络连通性探针（基于异步 TCP socket 握手）。"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=2.5,
        )
        writer.close()
        await writer.wait_closed()
        return True, "TCP 握手成功"
    except TimeoutError:
        return False, "TCP 连接超时 (主机可能离线或被防火墙拦截)"
    except Exception as exc:
        return False, f"TCP 连接拒绝或网络不可达: {exc}"


class FleetSixStateDiagnoser:
    """分布式机队节点六态自省诊断引擎。

    严格遵循五级渐进式排障流水线：
    Physical Network -> Credential Auth -> Gateway Daemon -> Runner Executor -> Provider Quota.
    """

    def __init__(
        self,
        *,
        physical_probe: PhysicalProbeFn | None = None,
        credential_probe: CredentialProbeFn | None = None,
        gateway_probe: GatewayProbeFn | None = None,
        runner_probe: RunnerProbeFn | None = None,
        provider_probe: ProviderProbeFn | None = None,
    ) -> None:
        self._physical_probe = physical_probe or default_physical_probe
        self._credential_probe = credential_probe
        self._gateway_probe = gateway_probe
        self._runner_probe = runner_probe
        self._provider_probe = provider_probe

    async def diagnose(self, target: FleetNodeTarget) -> FleetDiagnosisReport:
        """对目标节点执行全流程自省诊断，输出六态归因报告。"""
        stages: list[ProbeStageResult] = []

        # -------------------------------------------------------------
        # 1. 物理网络连通性 (Physical Network)
        # -------------------------------------------------------------
        t0 = time.perf_counter()
        phys_ok, phys_msg = await self._physical_probe(target.host, target.port)
        latency = (time.perf_counter() - t0) * 1000.0

        stages.append(
            ProbeStageResult(
                stage=ProbeStage.PHYSICAL_NETWORK,
                passed=phys_ok,
                latency_ms=latency,
                message=phys_msg,
            )
        )

        if not phys_ok:
            return FleetDiagnosisReport(
                node_id=target.node_id,
                node_name=target.node_name,
                state=FleetNodeState.OFFLINE,
                root_cause=f"物理网络中断或主机离线 ({phys_msg})",
                recommended_action="请检查目标主机电源、局域网/公网连接以及安全组端口放行配置。",
                stages=stages,
            )

        # -------------------------------------------------------------
        # 2. 身份凭证鉴权与配置 (Credential & Auth)
        # -------------------------------------------------------------
        if self._credential_probe:
            t0 = time.perf_counter()
            cred_ok, cred_msg = await self._credential_probe(target)
            latency = (time.perf_counter() - t0) * 1000.0

            stages.append(
                ProbeStageResult(
                    stage=ProbeStage.CREDENTIAL_AUTH,
                    passed=cred_ok,
                    latency_ms=latency,
                    message=cred_msg,
                )
            )

            if not cred_ok:
                return FleetDiagnosisReport(
                    node_id=target.node_id,
                    node_name=target.node_name,
                    state=FleetNodeState.MISCONFIGURED,
                    root_cause=f"节点凭据校验或 TLS 握手失败 ({cred_msg})",
                    recommended_action="请核对节点配置文件中的主机密钥 (Token/SSH Key) 与证书指纹。",
                    stages=stages,
                )

        # -------------------------------------------------------------
        # 3. 网关守护进程 (Gateway Daemon)
        # -------------------------------------------------------------
        if self._gateway_probe:
            t0 = time.perf_counter()
            gw_ok, gw_msg = await self._gateway_probe(target)
            latency = (time.perf_counter() - t0) * 1000.0

            stages.append(
                ProbeStageResult(
                    stage=ProbeStage.GATEWAY_DAEMON,
                    passed=gw_ok,
                    latency_ms=latency,
                    message=gw_msg,
                )
            )

            if not gw_ok:
                return FleetDiagnosisReport(
                    node_id=target.node_id,
                    node_name=target.node_name,
                    state=FleetNodeState.GATEWAY_STOPPED,
                    root_cause=f"目标主机网络正常，但 Myrm 守护进程未启动或已崩溃 ({gw_msg})",
                    recommended_action="请在远程主机终端登录并执行 `./myrm start` 启动服务端守护进程。",
                    stages=stages,
                )

        # -------------------------------------------------------------
        # 4. 沙箱执行器状态 (Runner Executor)
        # -------------------------------------------------------------
        if self._runner_probe:
            t0 = time.perf_counter()
            runner_ok, runner_msg = await self._runner_probe(target)
            latency = (time.perf_counter() - t0) * 1000.0

            stages.append(
                ProbeStageResult(
                    stage=ProbeStage.RUNNER_EXECUTOR,
                    passed=runner_ok,
                    latency_ms=latency,
                    message=runner_msg,
                )
            )

            if not runner_ok:
                return FleetDiagnosisReport(
                    node_id=target.node_id,
                    node_name=target.node_name,
                    state=FleetNodeState.RUNNER_BROKEN,
                    root_cause=f"网关服务正常，但底层 Agent 沙箱环境崩溃 ({runner_msg})",
                    recommended_action="请检查远程 Docker/Container 守护进程状态，或清理挂起的沙箱实例。",
                    stages=stages,
                )

        # -------------------------------------------------------------
        # 5. 上游模型供应商配额与健康 (Provider Quota / Health)
        # -------------------------------------------------------------
        if self._provider_probe:
            t0 = time.perf_counter()
            status_code, payload = await self._provider_probe(target)
            latency = (time.perf_counter() - t0) * 1000.0

            classification = classify_provider_error(
                status_code,
                payload,
                provider_name=target.provider_name,
                model_name=target.model_name,
            )

            prov_ok = not classification.is_provider_issue
            prov_msg = "Provider 就绪且配额充足" if prov_ok else classification.root_cause

            stages.append(
                ProbeStageResult(
                    stage=ProbeStage.PROVIDER_QUOTA,
                    passed=prov_ok,
                    latency_ms=latency,
                    message=prov_msg,
                    details={"status_code": status_code, "category": classification.category.value},
                )
            )

            if not prov_ok:
                return FleetDiagnosisReport(
                    node_id=target.node_id,
                    node_name=target.node_name,
                    state=FleetNodeState.PROVIDER_UNAVAILABLE,
                    root_cause=classification.root_cause,
                    recommended_action=classification.recommended_action,
                    stages=stages,
                )

        # -------------------------------------------------------------
        # 全部阶段通过 -> 判定为 ONLINE
        # -------------------------------------------------------------
        return FleetDiagnosisReport(
            node_id=target.node_id,
            node_name=target.node_name,
            state=FleetNodeState.ONLINE,
            root_cause="节点全栈健康",
            recommended_action="状态良好，可随时调度执行任务。",
            stages=stages,
        )
