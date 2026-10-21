"""动作后果分级容灾与应急人工接管矩阵类型定义模块.

本模块定义动作破坏力三级矩阵、鉴权网关状态、分级处置指令及应急接管卡片的核心数据模型。
严禁使用 Any 类型，确保完全强类型化。

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ActionImpactLevel
- AuthGatewayStatus
- FailSafeDisposition
- ActionImpactMetadata
- EmergencyTakeoverCard
- FailSafeEvaluationResult

[POS]
动作后果分级容灾与应急人工接管矩阵类型定义模块.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ActionImpactLevel(StrEnum):
    """动作后果破坏力分级枚举."""

    LEVEL_1_LOW = "level_1_low"  # 低危 · 局部只读与信息检索（文件读取/文档搜索/沙箱探测）
    LEVEL_2_MEDIUM = "level_2_medium"  # 中危 · 沙箱内部修改与局部测试（代码编写/临时文件/单测运行）
    LEVEL_3_HIGH = "level_3_high"  # 高危 · 外部副作用与破坏性操作（DB删除修改/支付/邮件群发/生产推送）


class AuthGatewayStatus(StrEnum):
    """上游鉴权网关/企业 IAM 服务的健康状态枚举."""

    HEALTHY = "healthy"  # 正常可用
    TIMEOUT = "timeout"  # 网关请求超时
    SERVICE_UNAVAILABLE = "service_unavailable"  # 500/503 或网络完全中断
    CIRCUIT_BROKEN = "circuit_broken"  # 熔断器拦截状态


class FailSafeDisposition(StrEnum):
    """分级容灾判决指令动作枚举."""

    ALLOW_NORMAL = "allow_normal"  # 正常放行（鉴权服务健康且校验通过）
    DENY_UNAUTHORIZED = "deny_unauthorized"  # 鉴权服务正常工作但用户权限不足被显式拒绝
    FAIL_OPEN_DEGRADED = "fail_open_degraded"  # 柔性降级放行（限 Level 1 低危只读，产生审计警报）
    QUARANTINED_OPEN = "quarantined_open"  # 沙箱写时复制隔离放行（限 Level 2，在 CoW 隔离区执行）
    FAIL_CLOSE_BLOCKED = "fail_close_blocked"  # 严格物理熔断阻断（Level 3 高危，绝对禁止执行）
    EMERGENCY_TAKEOVER_BYPASS = "emergency_takeover_bypass"  # 经授权人员 OTP 动态签署后单次特权放行


@dataclass(frozen=True)
class ActionImpactMetadata:
    """待执行动作或工具调用的元数据描述."""

    action_name: str
    impact_level: ActionImpactLevel
    target_resource: str
    is_idempotent: bool = True
    parameters: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EmergencyTakeoverCard:
    """当高危操作被 Fail-Close 阻断时生成的应急人工接管凭据卡片."""

    takeover_id: str
    action_name: str
    impact_level: ActionImpactLevel
    target_resource: str
    blocked_reason: str
    required_role: str
    expected_token_hash: str
    created_at_ms: float = field(default_factory=lambda: time.time() * 1000)


@dataclass(frozen=True)
class FailSafeEvaluationResult:
    """分级容灾调度器的综合评估决策结果."""

    disposition: FailSafeDisposition
    action_name: str
    impact_level: ActionImpactLevel
    reason: str
    takeover_card: EmergencyTakeoverCard | None = None
    audit_alert: str | None = None
    quarantine_sandbox_id: str | None = None
