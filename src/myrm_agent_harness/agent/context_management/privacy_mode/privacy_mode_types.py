"""强类型契约定义：会话级隐私模式：卸除全部工具硬门禁套件。

[INPUT]
- 无外部动态依赖，定义隐私模式级别、工具拦截动作、拦截记录与配置契约。

[OUTPUT]
- PrivacyModeLevel: 会话级隐私模式级别枚举 (常规 / 仅禁记忆 / 卸除全部工具 / 双重严格隔离)
- ToolHardGateAction: 工具执行硬门禁动作枚举 (允许 / 隐私硬拒绝 / 预过滤收走)
- ToolCallInterceptRecord: 模型擅自 tool_call 拦截记录契约
- PrivacyBoundToolSet: 隐私模式绑定的工具集合契约
- PrivacyModeSessionConfig: 会话级隐私模式配置契约

[POS]
- 位于 context_management/privacy_mode/privacy_mode_types.py
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class PrivacyModeLevel(StrEnum):
    """会话级隐私模式分级。"""

    STANDARD = "standard"  # 常规模式：工具与记忆全开
    INCOGNITO_ONLY = "incognito_only"  # 仅无痕：禁用记忆写入/检索，但工具保留
    TOOLS_OFF_STRICT = "tools_off_strict"  # 严格隐私：收走全部工具，仅纯对话
    TOOLS_OFF_AND_INCOGNITO = "tools_off_and_incognito"  # 双重最高隔离：收走工具且禁用记忆


class ToolHardGateAction(StrEnum):
    """工具调用硬门禁仲裁动作。"""

    PERMITTED = "permitted"
    HARD_DENIED_TOOLS_OFF = "hard_denied_tools_off"
    STRIPPED_SILENTLY = "stripped_silently"


@dataclass(frozen=True)
class ToolCallInterceptRecord:
    """执行层硬拦截违规 tool_call 记录契约。"""

    tool_name: str
    tool_call_id: str
    arguments_snippet: str
    gate_action: ToolHardGateAction
    reason: str
    intercepted_at_iso: str


@dataclass(frozen=True)
class PrivacyBoundToolSet:
    """隐私模式下绑定的安全工具集大盘契约。"""

    original_tool_count: int
    exposed_tool_names: tuple[str, ...]
    is_tools_off: bool
    privacy_level: PrivacyModeLevel


@dataclass
class PrivacyModeSessionConfig:
    """会话级隐私模式配置契约。"""

    privacy_level: PrivacyModeLevel = PrivacyModeLevel.TOOLS_OFF_STRICT
    hard_reject_tool_calls: bool = True
    allowed_system_meta_tools: tuple[str, ...] = field(default_factory=tuple)
    rejection_notice_template: str = (
        "[PRIVACY_MODE_HARD_GATE: TOOLS_OFF]\n"
        "Execution of tool '{tool_name}' was rejected by the security layer. "
        "This session is operating in strict privacy mode: all external tools, MCP, "
        "Vault and filesystem actions are permanently disabled. "
        "Please provide a direct conversational answer based solely on current dialogue context."
    )
