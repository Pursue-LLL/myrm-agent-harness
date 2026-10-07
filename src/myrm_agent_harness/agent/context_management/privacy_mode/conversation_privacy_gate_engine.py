"""核心引擎实现：会话级隐私模式：卸除全部工具硬门禁与擅自调用拦截。

[INPUT]
- 依赖 privacy_mode_types.py 中的契约，标准库 datetime, re 等。

[OUTPUT]
- ConversationPrivacyGateEngine: 会话级隐私模式工具门禁与拦截中枢引擎

[POS]
- 位于 context_management/privacy_mode/conversation_privacy_gate_engine.py
"""

from datetime import datetime, timezone
from typing import Sequence

from .privacy_mode_types import (
    PrivacyBoundToolSet,
    PrivacyModeLevel,
    PrivacyModeSessionConfig,
    ToolCallInterceptRecord,
    ToolHardGateAction,
)


class ConversationPrivacyGateEngine:
    """会话级隐私模式工具门禁与拦截中枢引擎。

    彻底破除用户在处理敏感任务时，传统 incognito 仅禁止记忆写入/检索却依旧向模型
    暴露外部工具链（Vault、网页、MCP、本地文件）导致的数据泄露与模型擅自调用风险。
    """

    def __init__(self) -> None:
        # 拦截审计记录账本: session_id -> list[ToolCallInterceptRecord]
        self._intercept_history: dict[str, list[ToolCallInterceptRecord]] = {}

    def bind_tools_for_session(
        self,
        all_tools: Sequence[str],
        session_config: PrivacyModeSessionConfig,
    ) -> PrivacyBoundToolSet:
        """根据当前会话的隐私模式级别，决定向 LLM 暴露绑定的工具集。"""
        original_count = len(all_tools)
        level = session_config.privacy_level

        # 1. 严格收走全部工具级别 (TOOLS_OFF_STRICT 或 TOOLS_OFF_AND_INCOGNITO)
        if level in (
            PrivacyModeLevel.TOOLS_OFF_STRICT,
            PrivacyModeLevel.TOOLS_OFF_AND_INCOGNITO,
        ):
            # 仅保留显式白名单系统元工具（默认空集合）
            allowed_meta = session_config.allowed_system_meta_tools
            filtered_tools = tuple(t for t in all_tools if t in allowed_meta)
            return PrivacyBoundToolSet(
                original_tool_count=original_count,
                exposed_tool_names=filtered_tools,
                is_tools_off=True,
                privacy_level=level,
            )

        # 2. 常规或仅无痕模式 (STANDARD / INCOGNITO_ONLY)：全量暴露工具
        return PrivacyBoundToolSet(
            original_tool_count=original_count,
            exposed_tool_names=tuple(all_tools),
            is_tools_off=False,
            privacy_level=level,
        )

    def intercept_and_hard_gate_tool_call(
        self,
        tool_name: str,
        tool_args: str,
        session_config: PrivacyModeSessionConfig,
        session_id: str = "default_session",
        tool_call_id: str | None = None,
    ) -> tuple[bool, ToolCallInterceptRecord, str]:
        """执行层硬门禁：若模型擅自返回 tool_call，强制硬拒绝并生成上下文反馈。"""
        level = session_config.privacy_level
        is_tools_off_mode = level in (
            PrivacyModeLevel.TOOLS_OFF_STRICT,
            PrivacyModeLevel.TOOLS_OFF_AND_INCOGNITO,
        )
        is_whitelisted = tool_name in session_config.allowed_system_meta_tools
        now_iso = datetime.now(timezone.utc).isoformat()
        call_id = tool_call_id or f"call_{tool_name}"
        args_snippet = tool_args[:120].strip()

        # 1. 触发隐私模式硬门禁拒绝
        if is_tools_off_mode and not is_whitelisted and session_config.hard_reject_tool_calls:
            reason = (
                f"Session is running in {level.value} mode. "
                f"Tool '{tool_name}' is permanently blocked."
            )
            record = ToolCallInterceptRecord(
                tool_name=tool_name,
                tool_call_id=call_id,
                arguments_snippet=args_snippet,
                gate_action=ToolHardGateAction.HARD_DENIED_TOOLS_OFF,
                reason=reason,
                intercepted_at_iso=now_iso,
            )
            if session_id not in self._intercept_history:
                self._intercept_history[session_id] = []
            self._intercept_history[session_id].append(record)

            rejection_notice = session_config.rejection_notice_template.format(
                tool_name=tool_name
            )
            return True, record, rejection_notice

        # 2. 正常允许通行
        permit_record = ToolCallInterceptRecord(
            tool_name=tool_name,
            tool_call_id=call_id,
            arguments_snippet=args_snippet,
            gate_action=ToolHardGateAction.PERMITTED,
            reason="Tool allowed under current privacy policy.",
            intercepted_at_iso=now_iso,
        )
        return False, permit_record, ""

    def is_memory_write_permitted(
        self,
        session_config: PrivacyModeSessionConfig,
    ) -> bool:
        """判定当前会话隐私级别是否允许向长期记忆或 Wiki 写入事实。"""
        level = session_config.privacy_level
        # 只要开启了无痕 (INCOGNITO_ONLY 或 TOOLS_OFF_AND_INCOGNITO)，坚决禁止记忆落库
        if level in (
            PrivacyModeLevel.INCOGNITO_ONLY,
            PrivacyModeLevel.TOOLS_OFF_AND_INCOGNITO,
        ):
            return False
        return True

    def get_intercept_history(
        self,
        session_id: str,
    ) -> tuple[ToolCallInterceptRecord, ...]:
        """获取指定会话被硬门禁拦截的所有违规调用审计记录。"""
        records = self._intercept_history.get(session_id, [])
        return tuple(records)

    def clear_intercept_history(self, session_id: str) -> None:
        """清空会话拦截审计记录。"""
        if session_id in self._intercept_history:
            del self._intercept_history[session_id]
