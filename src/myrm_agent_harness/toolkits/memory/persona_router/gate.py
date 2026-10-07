"""Gatekeeper inspecting user turn intent to strictly suppress persona tokens in technical tasks.

[INPUT]
- toolkits.memory.persona_router.types::TaskIntentCategory (POS: Typed data contracts for the persona router
  subsystem.)

[OUTPUT]
- StyleSuppressionGate: Gatekeeper inspecting user turn intent to strictly suppress persona tokens in
  technical tasks.

[POS]
Gatekeeper inspecting user turn intent to strictly suppress persona tokens in technical tasks.
"""

import re

from myrm_agent_harness.toolkits.memory.persona_router.types import (
    TaskIntentCategory,
)

_EXPLICIT_TRIGGER_PATTERN = re.compile(
    r"(?:/about-me|@persona|以我的口吻|采用我的文风|用我的语气|带上我的风格|我的风格|按照我的习惯)",
    re.IGNORECASE,
)

_TECHNICAL_PATTERNS = [
    re.compile(r"```(?:bash|sh|zsh|python|rust|json|yaml|go|ts|js)?[\s\S]*?```"),
    re.compile(
        r"\b(?:docker|kubectl|git|bash|shell|python|pytest|cargo|pip|npm|pnpm|curl|wget|grep|make)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:代码|调试|脚本|编译|部署|单元测试|单测|报错|异常|traceback|排查|端口|网络故障|sql|查询)"
    ),
]

_CREATIVE_PATTERNS = [
    re.compile(
        r"(?:撰写|写一封|写个邮件|公关稿|文案|推文|通报|汇报|商业计划书|润色|周报|演讲稿|社交媒体|发朋友圈)"
    ),
    re.compile(
        r"\b(?:email|tweet|post|speech|newsletter|memo|announcement|draft|pitch)\b",
        re.IGNORECASE,
    ),
]


class StyleSuppressionGate:
    """Gatekeeper inspecting user turn intent to strictly suppress persona tokens in technical tasks."""

    def evaluate_intent(
        self, query: str
    ) -> tuple[bool, TaskIntentCategory, str]:
        """Evaluate query and return (should_suppress, intent_category, reason)."""
        cleaned = query.strip()
        if not cleaned:
            return (
                True,
                TaskIntentCategory.TECHNICAL_EXECUTION,
                "Empty query suppressed to preserve zero context waste.",
            )

        # Check 1: Explicit persona directive takes absolute primacy
        if _EXPLICIT_TRIGGER_PATTERN.search(cleaned):
            return (
                False,
                TaskIntentCategory.CREATIVE_COMMUNICATION,
                "Explicit /about-me or style trigger detected; suppression bypassed.",
            )

        # Check 2: Technical execution patterns -> 100% strict suppression
        for pat in _TECHNICAL_PATTERNS:
            if pat.search(cleaned):
                return (
                    True,
                    TaskIntentCategory.TECHNICAL_EXECUTION,
                    "Technical execution task detected (code/CLI/debug); persona 100% suppressed.",
                )

        # Check 3: Creative, business communication, or authoring patterns -> unsuppressed
        for pat in _CREATIVE_PATTERNS:
            if pat.search(cleaned):
                return (
                    False,
                    TaskIntentCategory.CREATIVE_COMMUNICATION,
                    "Creative or communication authoring task detected; persona style active.",
                )

        # Check 4: General query default -> suppress to prevent default context pollution
        return (
            True,
            TaskIntentCategory.GENERAL_QUERY,
            "General conversational query without explicit style demand; persona suppressed.",
        )
