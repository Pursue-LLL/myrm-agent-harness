"""长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关套件。

导出的主要类与契约：
- InboundMessageOverflowShield: 入站消息超长防御栅栏引擎
- InboundShieldConfig: 防爆栅栏配置契约
- InboundShieldResult: 防御拦截与指针注入结果契约
- InboundMountedDocument: 挂载入沙箱工作区的大文本元数据契约
- InboundPayloadClassification: 入站有效载荷分类枚举

[INPUT]
- agent.context_management.inbound_shield.inbound_overflow_shield::InboundMessageOverflowShield (POS:
  核心引擎实现：长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关。)
- agent.context_management.inbound_shield.inbound_shield_types::InboundMountedDocument,
  InboundPayloadClassification, InboundShieldConfig, InboundShieldResult (POS: 强类型契约定义：长文本入站防御性分页挂载、大消息防爆
  Working Memory 与智能摘要网关套件。)

[OUTPUT]
- Re-exports: InboundMessageOverflowShield, InboundMountedDocument, InboundPayloadClassification,
  InboundShieldConfig, InboundShieldResult

[POS]
长文本入站防御性分页挂载、大消息防爆 Working Memory 与智能摘要网关套件。
"""

from .inbound_overflow_shield import InboundMessageOverflowShield
from .inbound_shield_types import (
    InboundMountedDocument,
    InboundPayloadClassification,
    InboundShieldConfig,
    InboundShieldResult,
)

__all__ = [
    "InboundMessageOverflowShield",
    "InboundMountedDocument",
    "InboundPayloadClassification",
    "InboundShieldConfig",
    "InboundShieldResult",
]
