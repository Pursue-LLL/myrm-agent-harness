"""会话级隐私模式：卸除全部工具硬门禁套件。

导出的主要类与契约：
- ConversationPrivacyGateEngine: 会话级隐私模式工具门禁与拦截中枢引擎
- PrivacyBoundToolSet: 隐私模式绑定的工具集合契约
- PrivacyModeLevel: 会话级隐私模式分级枚举
- PrivacyModeSessionConfig: 会话级隐私模式配置契约
- ToolCallInterceptRecord: 执行层硬拦截违规 tool_call 记录契约
- ToolHardGateAction: 工具执行硬门禁动作枚举
"""

from .conversation_privacy_gate_engine import ConversationPrivacyGateEngine
from .privacy_mode_types import (
    PrivacyBoundToolSet,
    PrivacyModeLevel,
    PrivacyModeSessionConfig,
    ToolCallInterceptRecord,
    ToolHardGateAction,
)

__all__ = [
    "ConversationPrivacyGateEngine",
    "PrivacyBoundToolSet",
    "PrivacyModeLevel",
    "PrivacyModeSessionConfig",
    "ToolCallInterceptRecord",
    "ToolHardGateAction",
]
