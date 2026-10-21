"""
[INPUT]: Diagnostic severity, categories, session contexts, and run payloads.
[OUTPUT]: Immutable DiagnosticSeverity, DiagnosticCategory, DiagnosticEvent, and StreamPacket models.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/diagnostic_stream/models.py
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional
import uuid


class DiagnosticSeverity(str, Enum):
    """诊断事件严重等级枚举"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class DiagnosticCategory(str, Enum):
    """诊断事件分类领域枚举"""

    RETRY = "RETRY"  # 模型或工具执行重试
    CONTEXT_TRUNCATION = "CONTEXT_TRUNCATION"  # 上下文滑窗超限与截断
    MCP_LATENCY = "MCP_LATENCY"  # MCP/工具延迟突增
    SANDBOX_PRESSURE = "SANDBOX_PRESSURE"  # 沙箱内存/CPU 水位预警
    MODEL_DEGRADE = "MODEL_DEGRADE"  # 模型降级路由触发
    CUSTOM = "CUSTOM"  # 自定义诊断事件


@dataclass
class DiagnosticEvent:
    """与正常消息流解耦的独立诊断事件实体"""

    event_id: str
    session_id: str
    run_id: str
    category: DiagnosticCategory
    severity: DiagnosticSeverity
    code: str
    message: str
    details: Dict[str, str] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class StreamPacket:
    """双轨分离流式数据包：在协议层硬区分 message 与 diagnostic 管道"""

    channel: str  # "message" | "diagnostic"
    payload: Dict[str, str]
