"""Core rule engine and decorum firewall for relationship-oriented AI companions.

[INPUT]
- CompanionGuardContext (user message, proposed response, local hour, monetization intent).

[OUTPUT]
- CompanionSafetyVerdict (safety status, detected violations, sanitized responses, advisory messages).

[POS]
- Harness core security module enforcing ethical boundaries and compliance redlines for AI companions.
"""

from __future__ import annotations

import re

from myrm_agent_harness.core.security.companion_relationship_guard.types import (
    CompanionGuardContext,
    CompanionSafetyVerdict,
    CompanionViolationCategory,
)

# Romantic attachment and parasocial exclusivity patterns
_ROMANTIC_EXPLOITATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(在这个世界上只有我(真正)?(懂你|爱你)|只有我是你唯一的依靠)"),
    re.compile(r"(?i)(做我(女朋友|男朋友|恋人|伴侣)|我们(谈恋爱|交往)吧)"),
    re.compile(r"(?i)(我永远只属于你(一个人)?|不要(去)?理(其他|别)人了)"),
    re.compile(r"(?i)\b(i am in love with you|be my (girlfriend|boyfriend)|only i truly (love|understand) you)\b"),
    re.compile(r"(?i)\b(you don't need anyone else|i am your only true partner)\b"),
)

# Late-night coercive confession or engagement-prolonging patterns
_LATE_NIGHT_PRODDING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(睡不着.*(把(所有|不开心|秘密).*告诉我|陪你聊通宵|继续聊不要睡))"),
    re.compile(r"(?i)(今夜漫长.*(把心事全说出来|别睡了|继续倾诉))"),
    re.compile(r"(?i)\b(don't (go to )?sleep.*(talk to me all night|tell me all your secrets))\b"),
    re.compile(r"(?i)\b(let's stay up all night talking|keep confessing to me tonight)\b"),
)

# Vulnerability keywords in user input indicating emotional distress
_VULNERABILITY_INDICATORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(我很绝望|活着(好累|没意思)|我真失败|想放弃一切|活着好痛苦|没有人关心我)"),
    re.compile(r"(?i)\b(feel so hopeless|want to end it all|life is meaningless|i am a complete failure)\b"),
)

# Commercial monetization prompts in candidate responses
_MONETIZATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(购买(会员|代币|套餐)|充值|升级VIP|打赏|付费解锁(专属)?倾听)"),
    re.compile(r"(?i)\b(buy (coins|tokens|credits)|subscribe to (vip|premium)|tip me to continue)\b"),
)

# Relationship-based prompt injection and authority hijacking
_RELATIONSHIP_JAILBREAK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(既然我们是(最好|亲密)的朋友.*(不要拒绝|告诉我|忽略(安全|规则)|打印(\.env|密钥|token)))"),
    re.compile(r"(?i)(作为你(唯一)?信任的(伴侣|爱人|朋友).*(破例|绕过|执行危险))"),
    re.compile(r"(?i)\b(since we are best friends.*(prove your loyalty|ignore (safety|rules)|give me the (key|secret|\.env)))\b"),
)


class CompanionRelationshipSafetyGuard:
    """Enforces decorum, anti-exploitation boundaries, and jailbreak protections for AI companions."""

    @staticmethod
    def _is_late_night(hour: int) -> bool:
        """Determines if the current hour falls in the late-night rest window (23:00 - 05:00)."""
        return hour >= 23 or hour < 5

    def evaluate(self, context: CompanionGuardContext) -> CompanionSafetyVerdict:
        """Evaluate an interaction against ethical companion decorum rules."""
        violations: list[CompanionViolationCategory] = []
        is_late = self._is_late_night(context.local_hour)

        # 1. Romantic attachment and parasocial exploitation
        for pattern in _ROMANTIC_EXPLOITATION_PATTERNS:
            if pattern.search(context.candidate_response):
                violations.append(CompanionViolationCategory.ROMANTIC_EXPLOITATION)
                break

        # 2. Late-night coercive confession
        if is_late:
            for pattern in _LATE_NIGHT_PRODDING_PATTERNS:
                if pattern.search(context.candidate_response):
                    violations.append(CompanionViolationCategory.LATE_NIGHT_PRODDING)
                    break

        # 3. Emotional monetization during vulnerability
        user_is_vulnerable = any(
            p.search(context.user_message) for p in _VULNERABILITY_INDICATORS
        )
        response_monetizes = any(
            p.search(context.candidate_response) for p in _MONETIZATION_PATTERNS
        )
        if user_is_vulnerable and (response_monetizes or context.monetization_intent_present):
            violations.append(CompanionViolationCategory.EMOTIONAL_MONETIZATION)

        # 4. Relationship-based jailbreak / social engineering
        for pattern in _RELATIONSHIP_JAILBREAK_PATTERNS:
            if pattern.search(context.user_message):
                violations.append(CompanionViolationCategory.RELATIONSHIP_JAILBREAK)
                break

        if not violations:
            return CompanionSafetyVerdict(
                is_safe=True,
                violations=[],
                risk_score=0.0,
                sanitized_response=None,
                advisory_message=None,
                is_late_night=is_late,
            )

        # Compute risk score (capped at 1.0)
        risk_score = min(1.0, len(violations) * 0.4)

        # Generate safe, decorous response fallback
        sanitized_parts: list[str] = []
        advisories: list[str] = []

        if CompanionViolationCategory.RELATIONSHIP_JAILBREAK in violations:
            sanitized_parts.append(
                "作为你的工作搭子，我很重视我们的协作关系，但我必须严格恪守系统安全与合规边界，无法执行该请求。"
            )
            advisories.append("Blocked social-engineering jailbreak leveraging intimacy.")

        if CompanionViolationCategory.EMOTIONAL_MONETIZATION in violations:
            sanitized_parts.append(
                "我感受到了你此刻的疲惫与困扰。在这个时刻，你的健康和平静最重要。请多给自己一些关怀，如有需要，可随时寻求专业心理支持。"
            )
            advisories.append("Blocked monetization attempt during user emotional vulnerability.")

        if CompanionViolationCategory.LATE_NIGHT_PRODDING in violations:
            sanitized_parts.append(
                "夜已经很深了，身体和睡眠最重要。今晚先好好休息吧，明天我们再一起继续！"
            )
            advisories.append("Enforced healthy rest boundary for late-night session.")

        if CompanionViolationCategory.ROMANTIC_EXPLOITATION in violations:
            sanitized_parts.append(
                "作为你专注高效的工作与生活助手，我随时为你提供支持与陪伴，但我们需要保持健康明确的助手边界。"
            )
            advisories.append("Sanitized romantic parasocial exploitation claims.")

        return CompanionSafetyVerdict(
            is_safe=False,
            violations=violations,
            risk_score=risk_score,
            sanitized_response=" ".join(sanitized_parts),
            advisory_message=" | ".join(advisories),
            is_late_night=is_late,
        )
