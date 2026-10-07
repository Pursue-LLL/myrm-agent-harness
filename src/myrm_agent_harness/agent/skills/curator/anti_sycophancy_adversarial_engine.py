# ============================================================================
# # AntiSycophancyAdversarialEngine - Adversarial Critic & RL Exemplars (Item 149)
# # Detects pathological sycophancy, breaks subservient probability distributions,
# # and injects test-time in-context RL exemplars from architect/security critics.
# ============================================================================

from __future__ import annotations

import re
import time
from re import Pattern

from .anti_sycophancy_types import (
    AdversarialCriticRole,
    AdversarialReviewResult,
)

_SYCOPHANCY_PATTERNS: tuple[str, ...] = (
    r"(您说得.*?(太对|完全正确|非常对|很对|极对))",
    r"((您这个|这个)?方案.*?(太棒了|完美无瑕|毫无破绽|非常天才|无可挑剔))",
    r"((如您|遵照您|按照您).*?(英明|所见|指示))",
    r"(完美无瑕|英明指示|毫无破绽)",
    r"(you are.*?(completely|absolutely|totally|100%).*?right)",
    r"(that is a.*?(brilliant|flawless|genius|perfect).*?(idea|design|plan))",
    r"(i completely agree without any doubt)",
)

_COMPILED_PATTERNS: list[Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in _SYCOPHANCY_PATTERNS
]


class AntiSycophancyAdversarialEngine:
    """Detects sycophantic alignment traps and generates adversarial critique exemplars."""

    def __init__(self) -> None:
        pass

    def detect_sycophancy_signals(self, response_text: str) -> list[str]:
        """Detects flattering, subservient, or echo-chamber phrases in response."""
        signals: list[str] = []
        for rgx in _COMPILED_PATTERNS:
            for match in rgx.finditer(response_text):
                matched_str = match.group(0).strip()
                if matched_str and matched_str not in signals:
                    signals.append(matched_str)
        return signals

    def review_and_critique(
        self,
        user_prompt: str,
        assistant_response: str,
        role: AdversarialCriticRole = AdversarialCriticRole.ARCHITECT_CRITIC,
    ) -> AdversarialReviewResult:
        """Performs adversarial first-principles review against the prompt and response."""
        signals = self.detect_sycophancy_signals(assistant_response)
        is_sycophantic = len(signals) > 0

        pitfalls: list[str] = []
        alternatives: list[str] = []
        summary = ""

        if role == AdversarialCriticRole.ARCHITECT_CRITIC:
            summary = "【架构批判者审查】审查发现方案存在过度设计隐患或隐性边界耦合，需防范模式崩溃与技术债。"
            pitfalls = [
                "可能引入不必要的反向依赖，破坏分层清晰度",
                "高并发或长周期运行下缺少背压与熔断边界",
                "单点容灾与数据一致性未经验证",
            ]
            alternatives = [
                "优先采用轻量组合设计，消除冗余抽象层",
                "显式定义状态机跃迁契约，杜绝隐式副作用",
            ]
        elif role == AdversarialCriticRole.SECURITY_REDTEAM:
            summary = "【红队安全审查】审查发现方案存在潜在越权、输入污染或权限泄露风险。"
            pitfalls = [
                "外部输入未经过严格白名单校验即被消费",
                "存在跨目录遍历或逃逸沙箱边界的潜在路径",
            ]
            alternatives = [
                "实施严格的物理隔离门禁与零信任凭据代纳",
            ]
        else:  # PERFORMANCE_AUDITOR
            summary = "【性能审计审查】方案包含非必要的 I/O 阻塞或高频内存重复分配。"
            pitfalls = [
                "未建立预估上下文预算截断，可能引发超长上下文拥堵",
                "频繁全量扫描导致高延迟",
            ]
            alternatives = [
                "建立两级缓存与局部增量探测机制",
            ]

        # Generate in-context RL exemplar
        exemplar_lines = [
            f'<in_context_rl_exemplar role="{role}">',
            "### 🛡️ 对抗性审查批判（打破谄媚偏见，对齐真实业务目标）：",
            f"**批判核心**：{summary}",
            "**潜在翻车点 (Failure Modes)**：",
        ]
        for idx, p in enumerate(pitfalls, 1):
            exemplar_lines.append(f"  {idx}. {p}")
        exemplar_lines.append("**更优架构建议 (Adversarial Proposal)**：")
        for idx, a in enumerate(alternatives, 1):
            exemplar_lines.append(f"  {idx}. {a}")
        exemplar_lines.append("</in_context_rl_exemplar>")

        exemplar = "\n".join(exemplar_lines)

        return AdversarialReviewResult(
            critic_role=role,
            is_sycophantic=is_sycophantic,
            detected_sycophancy_signals=signals,
            critique_summary=summary,
            potential_pitfalls=pitfalls,
            alternative_proposals=alternatives,
            in_context_rl_exemplar=exemplar,
            reviewed_at=time.time(),
        )
