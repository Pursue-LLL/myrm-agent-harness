"""
[INPUT]: Messages sequences, system/memory/workspace context strings, window capacity, and provider prompt tokens.
[OUTPUT]: ContextBreakdownSnapshot, ContextCategoryShare, ContextAlertLevel, and ContextBreakdownResolver.
[POS]: myrm_agent_harness/observability/context_breakdown/models.py
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Dict, List, Optional, Tuple, Union


class ContextAlertLevel(str, Enum):
    NORMAL = "NORMAL"          # < 60%: 表现优良，注意力集中
    WARNING_60 = "WARNING_60"  # 60% ~ 90%: 建议压缩或开启新任务
    CRITICAL_90 = "CRITICAL_90"# >= 90%: 触发自动压缩或硬熔断


@dataclass(frozen=True)
class ContextCategoryShare:
    category: str
    label_zh: str
    estimated_tokens: int
    percentage: float
    color_hex: str


@dataclass(frozen=True)
class ContextBreakdownSnapshot:
    total_window_tokens: int
    provider_actual_tokens: int
    estimated_sum_tokens: int
    usage_ratio_pct: float
    alert_level: ContextAlertLevel
    alert_message: str
    categories: Dict[str, ContextCategoryShare]


# 真实系统中的注入标签正则与匹配模式
_RE_MEMORY = re.compile(r"<user_memory_context[\s\S]*?</user_memory_context>", re.IGNORECASE)
_RE_WORKSPACE = re.compile(r"<workspace_context[\s\S]*?</workspace_context>", re.IGNORECASE)
_RE_SNAPSHOT = re.compile(r"<sandbox_environment_snapshot[\s\S]*?</sandbox_environment_snapshot>", re.IGNORECASE)
_RE_SKILLS = re.compile(r"<bound_skills[\s\S]*?</bound_skills>", re.IGNORECASE)
_RE_SYSTEM_TAG = re.compile(r"<system_prompt[\s\S]*?</system_prompt>", re.IGNORECASE)


def _approx_token_count(text: str) -> int:
    """高性能启发式 Token 估算：中文约 1.5 chars/token，英文代码约 4 chars/token。"""
    if not text:
        return 0
    # 统计中文字符
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars * 0.7 + other_chars * 0.25) + 1


class ContextBreakdownResolver:
    """高精度上下文 Token 七分类解析器与 60% 警戒线决策引擎。

    精确识别真实系统中的注入标签与消息类型，消除 69% 记录余量为 0 的历史黑盒。
    """

    def resolve(
        self,
        *,
        system_content: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        tools_schema_tokens: int = 0,
        provider_actual_tokens: int = 0,
        total_window_tokens: int = 128000,
    ) -> ContextBreakdownSnapshot:
        """从各注入源解析细分用量，并与提供商实际上报对比。"""
        system_prompt_tokens = 0
        memory_tokens = 0
        workspace_tokens = 0
        skills_tokens = 0
        tool_results_tokens = 0
        chat_messages_tokens = 0

        # 1. 扫描 system_content 中的注入标记
        full_sys_text = system_content or ""

        # 提取记忆
        for match in _RE_MEMORY.finditer(full_sys_text):
            memory_tokens += _approx_token_count(match.group(0))
        full_sys_text = _RE_MEMORY.sub("", full_sys_text)

        # 提取工作区与沙箱快照
        for match in _RE_WORKSPACE.finditer(full_sys_text):
            workspace_tokens += _approx_token_count(match.group(0))
        full_sys_text = _RE_WORKSPACE.sub("", full_sys_text)

        for match in _RE_SNAPSHOT.finditer(full_sys_text):
            workspace_tokens += _approx_token_count(match.group(0))
        full_sys_text = _RE_SNAPSHOT.sub("", full_sys_text)

        # 剩余纯系统提示词
        system_prompt_tokens = _approx_token_count(full_sys_text)

        # 2. 扫描 messages 序列
        if messages:
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")

                if role in ("tool", "tool_result"):
                    tool_results_tokens += _approx_token_count(content)
                    continue

                # 检查首条用户消息中的 <bound_skills>
                skill_matches = _RE_SKILLS.findall(content)
                if skill_matches:
                    for sm in skill_matches:
                        skills_tokens += _approx_token_count(sm)
                    content = _RE_SKILLS.sub("", content)

                # 其余作为正常对话消息
                chat_messages_tokens += _approx_token_count(content)

        # 3. 统计各分项估算值之和
        subtotal_estimated = (
            system_prompt_tokens
            + memory_tokens
            + workspace_tokens
            + skills_tokens
            + tools_schema_tokens
            + tool_results_tokens
            + chat_messages_tokens
        )

        # 4. 锚定提供商总量：若提供商实际上报大于估算，计算残余量；否则以估算为基准
        effective_total = max(provider_actual_tokens, subtotal_estimated)
        residual_tokens = max(0, provider_actual_tokens - subtotal_estimated) if provider_actual_tokens > 0 else 0
        norm_base = max(1, effective_total)

        # 5. 组装七分类
        categories: Dict[str, ContextCategoryShare] = {
            "system_prompt": ContextCategoryShare(
                category="system_prompt",
                label_zh="系统设定 (System)",
                estimated_tokens=system_prompt_tokens,
                percentage=round((system_prompt_tokens / norm_base) * 100, 1),
                color_hex="#38bdf8",  # sky
            ),
            "memory": ContextCategoryShare(
                category="memory",
                label_zh="长期记忆 (Memory)",
                estimated_tokens=memory_tokens,
                percentage=round((memory_tokens / norm_base) * 100, 1),
                color_hex="#a855f7",  # purple
            ),
            "workspace": ContextCategoryShare(
                category="workspace",
                label_zh="工作区规则 (Rules)",
                estimated_tokens=workspace_tokens,
                percentage=round((workspace_tokens / norm_base) * 100, 1),
                color_hex="#3b82f6",  # blue
            ),
            "skills": ContextCategoryShare(
                category="skills",
                label_zh="技能目录 (Skills)",
                estimated_tokens=skills_tokens,
                percentage=round((skills_tokens / norm_base) * 100, 1),
                color_hex="#10b981",  # emerald
            ),
            "tools_schema": ContextCategoryShare(
                category="tools_schema",
                label_zh="工具定义 (Tools Schema)",
                estimated_tokens=tools_schema_tokens,
                percentage=round((tools_schema_tokens / norm_base) * 100, 1),
                color_hex="#06b6d4",  # cyan
            ),
            "tool_results": ContextCategoryShare(
                category="tool_results",
                label_zh="工具返回 (Tool Output)",
                estimated_tokens=tool_results_tokens,
                percentage=round((tool_results_tokens / norm_base) * 100, 1),
                color_hex="#f59e0b",  # amber
            ),
            "chat_messages": ContextCategoryShare(
                category="chat_messages",
                label_zh="对话历史 (Chat)",
                estimated_tokens=chat_messages_tokens,
                percentage=round((chat_messages_tokens / norm_base) * 100, 1),
                color_hex="#64748b",  # slate
            ),
        }
        if residual_tokens > 0:
            categories["residual"] = ContextCategoryShare(
                category="residual",
                label_zh="其他余量 (Residual)",
                estimated_tokens=residual_tokens,
                percentage=round((residual_tokens / norm_base) * 100, 1),
                color_hex="#71717a",  # zinc
            )

        # 6. 计算用量占比与警戒线等级
        usage_ratio = round((effective_total / max(1, total_window_tokens)) * 100, 2)
        if usage_ratio >= 90.0:
            alert_lvl = ContextAlertLevel.CRITICAL_90
            alert_msg = f"上下文已达 {usage_ratio}%，超过 90% 极高警戒线，系统将触发自动深度压缩！"
        elif usage_ratio >= 60.0:
            alert_lvl = ContextAlertLevel.WARNING_60
            alert_msg = f"上下文已用 {usage_ratio}%，跨越 60% 性能临界点（注意力衰减区间），建议主动压缩上下文或开启新任务。"
        else:
            alert_lvl = ContextAlertLevel.NORMAL
            alert_msg = f"上下文健康（已用 {usage_ratio}% / 上限 {total_window_tokens}），模型处于最佳注意力区间。"

        return ContextBreakdownSnapshot(
            total_window_tokens=total_window_tokens,
            provider_actual_tokens=provider_actual_tokens,
            estimated_sum_tokens=subtotal_estimated,
            usage_ratio_pct=usage_ratio,
            alert_level=alert_lvl,
            alert_message=alert_msg,
            categories=categories,
        )
