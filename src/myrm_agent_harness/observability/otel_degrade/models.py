"""
[INPUT]: OpenTelemetry installation presence, environment configuration, and intercept counters.
[OUTPUT]: Immutable OtelPostureState enum and OtelDegradeStatus diagnostics record.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/otel_degrade/models.py
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class OtelPostureState(str, Enum):
    """OpenTelemetry 探针运行态姿态枚举"""

    ACTIVE = "ACTIVE"  # OTel 已安装并正常活跃追踪
    DEGRADED_NO_OP = "DEGRADED_NO_OP"  # 依赖缺失或异常，静默降级为零开销 No-Op 空操作（业务零中断）
    DISABLED = "DISABLED"  # 显式环境变量关闭


@dataclass
class OtelDegradeStatus:
    """OpenTelemetry 优雅降级与运行时体征状态"""

    state: OtelPostureState
    is_otel_installed: bool
    degrade_reason: Optional[str]
    intercepted_spans_count: int
    intercepted_metrics_count: int
    last_probe_time: str
