"""
[INPUT]: Raw HTML/Markdown page text, URL paths, and optional llms.txt declarations.
[OUTPUT]: AeoPageDiagnostic reports with estimated tokens, failure root causes, and optimization suggestions.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/agentic_traffic/abandonment_sentinel.py
"""

import re
from typing import List

from .models import AbandonmentReason, AeoPageDiagnostic


class AgentAbandonmentSentinel:
    """
    Diagnoses documentation and API landing pages against Agent Engine Optimization (AEO)
    guidelines to pinpoint why coding agents bounce or fail to adopt the product within 500 tokens.
    """

    def diagnose_page(
        self,
        path: str,
        content: str,
        has_llms_txt_declared: bool = False,
    ) -> AeoPageDiagnostic:
        text = content or ""
        char_count = len(text)
        # Approximate token count: ~4 chars per token
        estimated_tokens = max(1, char_count // 4)

        reasons: List[AbandonmentReason] = []
        suggestions: List[str] = []
        score = 100

        # 1. Token overflow check (> 20,000 tokens)
        if estimated_tokens > 20000:
            reasons.append(AbandonmentReason.TOKEN_OVERFLOW_20K)
            suggestions.append(
                f"页面内容过长 ({estimated_tokens:,} Tokens > 20,000 阈值)，容易撑爆 Agent 上下文导致静默跳出，建议精简并模块化拆分"
            )
            score -= 30

        # 2. llms.txt missing check
        if not has_llms_txt_declared and not re.search(r"llms(-full)?\.txt", text, re.IGNORECASE):
            reasons.append(AbandonmentReason.LLMS_TXT_MISSING)
            suggestions.append(
                "未发现 /llms.txt 规范声明，Agent 只能在繁杂 HTML 中盲爬，建议在根目录暴露标准 llms.txt"
            )
            score -= 25

        # 3. First 500 tokens code & quickstart check
        first_2000_chars = text[:2000]
        has_code_in_first_500 = bool(
            "```" in first_2000_chars or "<code>" in first_2000_chars or "curl " in first_2000_chars or "import " in first_2000_chars
        )
        if not has_code_in_first_500:
            reasons.append(AbandonmentReason.FIRST_500_TOKENS_VAGUE)
            suggestions.append(
                "前 500 Tokens 缺乏立即可执行的代码示例或核心用法，容易导致 Coding Agent 在 400ms 内判定方案晦涩并静默放弃"
            )
            score -= 25

        # 4. SPA blank client rendering check
        is_client_blank = False
        if "<div id=\"root\"" in text or "<div id=\"app\"" in text:
            # Strip tags and check content density
            stripped = re.sub(r"<[^>]+>", "", text).strip()
            if len(stripped) < 200:
                is_client_blank = True
                reasons.append(AbandonmentReason.SPA_CLIENT_BLANK)
                suggestions.append(
                    "检测到纯 SPA 客户端渲染骨架，内容文本极短，无头 HTTP Agent 无法执行 JS 渲染，建议开启 SSR 或提供纯 Markdown 接口"
                )
                score -= 40

        if not reasons:
            reasons.append(AbandonmentReason.NONE)
            suggestions.append("页面 AEO 表现优秀，代码示例前置且结构精炼，适合 Agent 快速吸收与集成")

        final_score = max(0, min(100, score))

        return AeoPageDiagnostic(
            path=path,
            estimated_tokens=estimated_tokens,
            has_llms_txt_declared=has_llms_txt_declared,
            has_code_in_first_500_tokens=has_code_in_first_500,
            is_spa_client_blank=is_client_blank,
            suggested_actions=suggestions,
            abandonment_reasons=reasons,
            aeo_score=final_score,
        )
