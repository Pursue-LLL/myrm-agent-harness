"""方案否决与禁忌决策专属账本，前置拦截已被废弃的方案，彻底杜绝 AI 重复踩坑。

[INPUT]
- toolkits.memory.shared_bus.types::DecisionVetoSeverity, NegativeDecisionCheckResult, NegativeDecisionEntry
  (POS: 跨 Agent 共享记忆总线、并发连接池、背压守卫与方案否决账本的核心类型定义。)

[OUTPUT]
- NegativeDecisionLedger: 方案否决专属账本管理器。

[POS]
方案否决与禁忌决策专属账本，前置拦截已被废弃的方案，彻底杜绝 AI 重复踩坑。
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.toolkits.memory.shared_bus.types import (
    DecisionVetoSeverity,
    NegativeDecisionCheckResult,
    NegativeDecisionEntry,
)

_STOPWORDS: Final[set[str]] = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "from",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "使用",
    "采用",
    "方案",
    "我们",
    "进行",
    "这个",
    "那个",
    "对于",
}


class NegativeDecisionLedger:
    """方案否决专属账本管理器。"""

    def __init__(self) -> None:
        self._entries: dict[str, NegativeDecisionEntry] = {}

    def record_veto(self, entry: NegativeDecisionEntry) -> None:
        """记录一条被否决的方案决策。"""
        self._entries[entry.decision_id] = entry

    def remove_veto(self, decision_id: str) -> bool:
        """移除指定的否决记录（若存在）。"""
        if decision_id in self._entries:
            del self._entries[decision_id]
            return True
        return False

    def get_veto(self, decision_id: str) -> NegativeDecisionEntry | None:
        """根据 ID 获取否决记录。"""
        return self._entries.get(decision_id)

    def list_vetoes(self, scope: str | None = None) -> list[NegativeDecisionEntry]:
        """获取所有或指定作用域的否决记录。"""
        if scope is None:
            return list(self._entries.values())
        return [
            entry
            for entry in self._entries.values()
            if entry.scope == scope or entry.scope == "global"
        ]

    def clear(self) -> None:
        """清空所有记录。"""
        self._entries.clear()

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """对文本进行轻量分词并去除非关键虚词。"""
        normalized = text.lower()
        # 匹配英文单词或连续中文字符
        words = re.findall(r"[a-z0-9_-]+|[\u4e00-\u9fa5]{2,}", normalized)
        return {w for w in words if w not in _STOPWORDS and len(w) > 1}

    def check_veto_conflict(
        self, candidate_proposal: str, scope: str = "global"
    ) -> NegativeDecisionCheckResult:
        """前置筛查候选提案是否与历史否决记录冲突。"""
        if not candidate_proposal.strip() or not self._entries:
            return NegativeDecisionCheckResult(
                is_blocked=False,
                matched_entries=[],
                guard_prompt_slice="",
                rejection_summary="",
            )

        candidate_tokens = self._tokenize(candidate_proposal)
        matched: list[NegativeDecisionEntry] = []

        for entry in self._entries.values():
            if entry.scope != "global" and entry.scope != scope:
                continue

            subject_lower = entry.decision_subject.lower()
            proposal_lower = candidate_proposal.lower()

            # 1. 包含匹配
            is_direct_match = (
                subject_lower in proposal_lower
                or (len(subject_lower) >= 3 and subject_lower in proposal_lower)
            )

            # 2. 核心词交集判定
            subject_tokens = self._tokenize(entry.decision_subject)
            token_overlap = (
                len(candidate_tokens & subject_tokens)
                if subject_tokens and candidate_tokens
                else 0
            )
            is_token_match = token_overlap >= max(1, len(subject_tokens) // 2)

            if is_direct_match or is_token_match:
                matched.append(entry)

        if not matched:
            return NegativeDecisionCheckResult(
                is_blocked=False,
                matched_entries=[],
                guard_prompt_slice="",
                rejection_summary="",
            )

        # 检查是否包含 HARD_BLOCK
        has_hard_block = any(
            e.severity == DecisionVetoSeverity.HARD_BLOCK for e in matched
        )
        guard_prompt = self.format_veto_guard_prompt(matched)
        rejection_summary = "; ".join(
            f"方案 '{e.decision_subject}' 已被否决: {e.veto_reason} (推荐替代: {e.alternative_chosen})"
            for e in matched
        )

        return NegativeDecisionCheckResult(
            is_blocked=has_hard_block,
            matched_entries=matched,
            guard_prompt_slice=guard_prompt,
            rejection_summary=rejection_summary,
        )

    @staticmethod
    def format_veto_guard_prompt(entries: list[NegativeDecisionEntry]) -> str:
        """生成面向模型的 [NEGATIVE DECISION GUARD] 注入警示切片。"""
        if not entries:
            return ""

        lines: list[str] = [
            "<!-- [NEGATIVE DECISION GUARD] 历史已否决禁忌方案警示 -->",
            "以下方案在历史决策中经过充分论证已被明确否定，严禁重复推荐已否决的方案：",
        ]
        for idx, item in enumerate(entries, start=1):
            severity_mark = (
                "[绝对禁止]"
                if item.severity == DecisionVetoSeverity.HARD_BLOCK
                else "[强烈预警]"
            )
            lines.append(
                f"{idx}. {severity_mark} 被否决主题: {item.decision_subject}\n"
                f"   - 否决原因: {item.veto_reason}\n"
                f"   - 既定替代方案: {item.alternative_chosen}"
            )
            if item.context_summary:
                lines.append(f"   - 技术背景代价: {item.context_summary}")

        lines.append("请严格遵从既定替代方案开展设计，杜绝重复提议已被否决的方案。")
        return "\n".join(lines)
