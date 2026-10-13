"""[INPUT]
- enum.StrEnum, dataclasses.dataclass, typing (Standard library types)

[OUTPUT]
- FleetNodeState: 六维状态枚举 (ONLINE, OFFLINE, MISCONFIGURED, PROVIDER_UNAVAILABLE, GATEWAY_STOPPED, RUNNER_BROKEN)
- ProbeStage: 探针阶段枚举
- ProbeStageResult: 单个探针阶段检测结果
- FleetDiagnosisReport: 完整的机队节点六态健康诊断报告
- FleetNodeTarget: 诊断目标节点契约

[POS]
myrm_agent_harness.observability.diagnostics.fleet_telemetry.models — 分布式机队六态健康诊断数据契约。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class FleetNodeState(StrEnum):
    """分布式机队节点六维精细化运行状态。"""

    ONLINE = "online"  # 全绿：网络连通、网关在线、沙箱运行正常、模型 Provider 就绪
    OFFLINE = "offline"  # 物理网络不通、主机断电或目标端口无法建立连接
    MISCONFIGURED = "misconfigured"  # 网络通但主机地址/端口/TLS 证书/认证密钥校验失败
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # 网络与服务通，但上游模型提供方 429 限流或 402 余额欠费
    GATEWAY_STOPPED = "gateway_stopped"  # 物理网络通，但目标机器上的 Myrm 服务端守护进程未运行
    RUNNER_BROKEN = "runner_broken"  # 网关正常，但底层沙箱执行器或代码解释器容器异常崩溃


class ProbeStage(StrEnum):
    """六态自省探针的五级渐进式流水线阶段。"""

    PHYSICAL_NETWORK = "physical_network"
    CREDENTIAL_AUTH = "credential_auth"
    GATEWAY_DAEMON = "gateway_daemon"
    RUNNER_EXECUTOR = "runner_executor"
    PROVIDER_QUOTA = "provider_quota"


@dataclass(frozen=True, slots=True)
class ProbeStageResult:
    """单个阶段探针的执行结果。"""

    stage: ProbeStage
    passed: bool
    latency_ms: float
    message: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "stage": self.stage.value,
            "passed": self.passed,
            "latency_ms": round(self.latency_ms, 2),
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class FleetDiagnosisReport:
    """机队节点六态精细化诊断报告。"""

    node_id: str
    node_name: str
    state: FleetNodeState
    root_cause: str
    recommended_action: str
    stages: list[ProbeStageResult]
    diagnosed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "state": self.state.value,
            "root_cause": self.root_cause,
            "recommended_action": self.recommended_action,
            "stages": [s.to_dict() for s in self.stages],
            "diagnosed_at": round(self.diagnosed_at, 3),
        }


@dataclass(frozen=True, slots=True)
class FleetNodeTarget:
    """待诊断机队节点信息。"""

    node_id: str
    node_name: str
    host: str
    port: int = 8000
    token: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
