# [INPUT]: AgentRoleTarget, IntentCategory, IntentRoutingDecision
# [OUTPUT]: UnifiedIntentDispatcher
# [POS]: agent/sub_agents/cross_examination/unified_intent_dispatcher.py

"""Unified single-entry intent dispatcher routing requests and suggesting cross-examination candidates.

[INPUT]
- AgentRoleTarget, IntentCategory, IntentRoutingDecision: Contract models.

[OUTPUT]
- UnifiedIntentDispatcher: Sub-millisecond rule-and-heuristic intent classification engine.

[POS]
Dispatcher layer in omni-agent unified dispatch and split cross-examination subsystem.
"""

from __future__ import annotations

import re

from .cross_exam_types import (
    AgentRoleTarget,
    IntentCategory,
    IntentRoutingDecision,
)


class UnifiedIntentDispatcher:
    """Classifies user intent from a unified prompt and decides whether cross-examination is warranted."""

    # High-risk / Destructive security patterns
    SECURITY_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"\b(?:rm\s+-rf|drop\s+table|delete\s+from|format\s+disk|mkfs|dd\s+if=)\b", re.IGNORECASE),
        re.compile(r"\b(?:sudo|chmod\s+777|chown|kill\s+-9|pkill)\b", re.IGNORECASE),
        re.compile(r"(?:生产数据库|删除所有|安全漏洞|注入攻击|提权|清空表|资金划转|转账)", re.IGNORECASE),
    )

    # Architectural trade-off / high divergence inquiry patterns
    ARCHITECTURAL_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?:架构选型|方案对比|权衡分析|vs|哪个更优|trade-off|pros\s+and\s+cons)", re.IGNORECASE),
        re.compile(r"(?:redis\s+vs\s+memcached|postgres\s+vs\s+mysql|kafka\s+vs\s+pulsar|rest\s+vs\s+grpc)", re.IGNORECASE),
        re.compile(r"(?:微服务还是单体|重构还是重写|技术选型|选哪个方案)", re.IGNORECASE),
    )

    # Deep research / literature search patterns
    RESEARCH_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?:调研|文献|最新进展|行业报告|现状分析|竞品分析|市场规模|论文|综述)", re.IGNORECASE),
        re.compile(r"\b(?:survey|literature|state\s+of\s+the\s+art|sota|whitepaper|market\s+share)\b", re.IGNORECASE),
    )

    # Coding / Development patterns
    CODING_PATTERNS: tuple[re.Pattern[str], ...] = (
        re.compile(r"(?:def\s+|class\s+|function|import\s+|refactor|debug|fix\s+bug|unit\s+test)", re.IGNORECASE),
        re.compile(r"(?:重构代码|写一个函数|修复报错|实现类|单元测试|排查异常|代码走查)", re.IGNORECASE),
        re.compile(r"\b(?:python|typescript|golang|rust|javascript|sql|regex|pytest)\b", re.IGNORECASE),
    )

    def route_intent(self, query: str) -> IntentRoutingDecision:
        """Analyze query text and synthesize optimal primary dispatch target and cross-exam suggestion."""
        trimmed = query.strip()
        if not trimmed:
            return IntentRoutingDecision(
                primary_agent=AgentRoleTarget.LOCAL_FAST,
                confidence=1.0,
                category=IntentCategory.GENERAL_QUICK_COMMAND,
                suggested_cross_exam_agents=(AgentRoleTarget.LOCAL_FAST,),
                is_cross_exam_candidate=False,
                reasoning="Empty or whitespace query defaults to local fast handler.",
            )

        # 1. High-risk security check (Priority 1)
        if any(p.search(trimmed) for p in self.SECURITY_PATTERNS):
            return IntentRoutingDecision(
                primary_agent=AgentRoleTarget.SECURITY_CRITIC,
                confidence=0.95,
                category=IntentCategory.SECURITY_HIGH_RISK,
                suggested_cross_exam_agents=(
                    AgentRoleTarget.SECURITY_CRITIC,
                    AgentRoleTarget.CODING_SPECIALIST,
                    AgentRoleTarget.ARCHITECT_PLANNER,
                ),
                is_cross_exam_candidate=True,
                reasoning="Detected potentially destructive or high-risk operational intent. Requires security critic cross-examination.",
            )

        # 2. Architectural decision check (High trade-off candidate)
        if any(p.search(trimmed) for p in self.ARCHITECTURAL_PATTERNS):
            return IntentRoutingDecision(
                primary_agent=AgentRoleTarget.ARCHITECT_PLANNER,
                confidence=0.90,
                category=IntentCategory.ARCHITECTURAL_DECISION,
                suggested_cross_exam_agents=(
                    AgentRoleTarget.ARCHITECT_PLANNER,
                    AgentRoleTarget.CODING_SPECIALIST,
                    AgentRoleTarget.SECURITY_CRITIC,
                ),
                is_cross_exam_candidate=True,
                reasoning="Detected multi-dimensional architectural trade-off inquiry. Strongly recommended for split cross-examination.",
            )

        # 3. Deep research / survey check
        if any(p.search(trimmed) for p in self.RESEARCH_PATTERNS):
            return IntentRoutingDecision(
                primary_agent=AgentRoleTarget.DEEP_RESEARCH,
                confidence=0.88,
                category=IntentCategory.RESEARCH_SURVEY,
                suggested_cross_exam_agents=(
                    AgentRoleTarget.DEEP_RESEARCH,
                    AgentRoleTarget.ARCHITECT_PLANNER,
                ),
                is_cross_exam_candidate=False,
                reasoning="Detected broad investigative or literature survey intent.",
            )

        # 4. Coding / Engineering development check
        if any(p.search(trimmed) for p in self.CODING_PATTERNS):
            return IntentRoutingDecision(
                primary_agent=AgentRoleTarget.CODING_SPECIALIST,
                confidence=0.85,
                category=IntentCategory.DEVELOPMENT_ENGINEERING,
                suggested_cross_exam_agents=(
                    AgentRoleTarget.CODING_SPECIALIST,
                    AgentRoleTarget.SECURITY_CRITIC,
                ),
                is_cross_exam_candidate=False,
                reasoning="Detected code implementation, debugging, or refactoring intent.",
            )

        # 5. Default fallback to lightweight local fast agent
        return IntentRoutingDecision(
            primary_agent=AgentRoleTarget.LOCAL_FAST,
            confidence=0.75,
            category=IntentCategory.GENERAL_QUICK_COMMAND,
            suggested_cross_exam_agents=(AgentRoleTarget.LOCAL_FAST,),
            is_cross_exam_candidate=False,
            reasoning="Routine command or conversational query routed to lightweight local fast assistant.",
        )
