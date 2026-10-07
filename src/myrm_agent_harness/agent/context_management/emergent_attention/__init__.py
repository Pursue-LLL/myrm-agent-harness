"""从用户行为中涌现的注意力清单、海量通知意图过滤器与言行错位智能对照模块。

[INPUT]
- .emergent_attention_types: 强类型数据模型与枚举
- .emergent_attention_engine: 核心注意力清单涌现与言行对照引擎

[OUTPUT]
- 统一向外导出公共契约与核心类。

[POS]
- 位于 context_management/emergent_attention/__init__.py
"""

from .emergent_attention_engine import EmergentAttentionEngine
from .emergent_attention_types import (
    ActionTraceEvent,
    EmergentAttentionDossier,
    EmergentAttentionItem,
    InboundNotification,
    IntentionActionDiffItem,
    IntentionActionDiffReport,
    NotificationSieveResult,
    SieveDecision,
    StatedIntention,
    UserActionTraceKind,
)

__all__ = [
    "ActionTraceEvent",
    "EmergentAttentionDossier",
    "EmergentAttentionEngine",
    "EmergentAttentionItem",
    "InboundNotification",
    "IntentionActionDiffItem",
    "IntentionActionDiffReport",
    "NotificationSieveResult",
    "SieveDecision",
    "StatedIntention",
    "UserActionTraceKind",
]
