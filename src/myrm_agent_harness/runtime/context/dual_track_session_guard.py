"""Dual-Track Session Scenario Context Isolator and Token Burn Guard.

Segregates developer sessions into DEV_TRACK (code indexing, execution, full workspace)
and THINKING_QA_TRACK (isolated, lightweight, low-cost reasoning).
Automatically throttles unintentional workspace context injection during general chat.

[INPUT]
- runtime.context.dual_track_session_guard_types::BurnGuardAction, BurnGuardDecision,
  DualTrackContextAssembly, IntentCategory, SessionScenarioTrack (POS: Type definitions for Dual-Track
  Session Scenario Context Isolator and Token Burn Guard.)

[OUTPUT]
- DualTrackSessionGuardHub: Coordinates system prompt assembly respecting track boundaries and burn guards.
- TokenBurnGuard: Safeguards user token quota from unintentional workspace tree attachment.
- UserIntentClassifier: Classifies user prompts into engineering development vs general chat/QA.

[POS]
Dual-Track Session Scenario Context Isolator and Token Burn Guard.
"""

from __future__ import annotations

import re
from typing import ClassVar

from myrm_agent_harness.runtime.context.dual_track_session_guard_types import (
    BurnGuardAction,
    BurnGuardDecision,
    DualTrackContextAssembly,
    IntentCategory,
    SessionScenarioTrack,
)

__all__ = [
    "BurnGuardAction",
    "BurnGuardDecision",
    "DualTrackContextAssembly",
    "DualTrackSessionGuardHub",
    "IntentCategory",
    "SessionScenarioTrack",
    "TokenBurnGuard",
    "UserIntentClassifier",
]


class UserIntentClassifier:
    """Classifies user prompts into engineering development vs general chat/QA."""

    _CODE_KEYWORDS: ClassVar[tuple[str, ...]] = (
        "def ",
        "class ",
        "function",
        "import ",
        "export ",
        "return ",
        "const ",
        "let ",
        "var ",
        "async ",
        "await ",
        "pytest",
        "unittest",
        "vitest",
        "npm ",
        "cargo ",
        "git ",
        "commit",
        "pull request",
        "stack trace",
        "traceback",
        "exception",
        "error:",
        "typeerror",
        "syntaxerror",
        "refactor",
        "debug",
        "compile",
        "build",
        "lint",
        "format",
        "单测",
        "重构",
        "调试",
        "函数",
        "报错",
        "异常",
        "编译",
        "依赖",
        "类",
    )

    _FILE_EXTENSIONS_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\b\w+\.(py|ts|tsx|js|jsx|rs|go|c|cpp|h|hpp|java|kt|rb|json|yaml|yml|toml|sql|md|html|css)\b",
        re.IGNORECASE,
    )

    _GENERAL_CHAT_PATTERNS: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(你好|您好|hi|hello|hey|早安|晚安|在吗)[\s!！?？\.]*$", re.IGNORECASE),
        re.compile(r"(写个周报|写封邮件|写邮件|润色|周报总结|写一封信|祝福语)", re.IGNORECASE),
        re.compile(r"(推荐几部|推荐电影|推荐书|讲个笑话|翻译成|是什么意思)", re.IGNORECASE),
    )

    @classmethod
    def classify_intent(cls, prompt: str) -> IntentCategory:
        """Determines if the prompt demands workspace code engineering or general reasoning."""
        stripped = prompt.strip()
        if not stripped:
            return IntentCategory.GENERAL_QA_OR_CHAT

        # Check explicit @file: notation or file extensions
        if "@file:" in stripped or cls._FILE_EXTENSIONS_PATTERN.search(stripped):
            return IntentCategory.ENGINEERING_DEV

        # Check code fence blocks
        if "```" in stripped:
            return IntentCategory.ENGINEERING_DEV

        # Check programming keywords
        lower_prompt = stripped.lower()
        if any(kw in lower_prompt for kw in cls._CODE_KEYWORDS):
            return IntentCategory.ENGINEERING_DEV

        # Check general greetings and non-code writing tasks
        for pattern in cls._GENERAL_CHAT_PATTERNS:
            if pattern.search(stripped):
                return IntentCategory.GENERAL_QA_OR_CHAT

        # If short and contains no code signals, bias towards general Q&A
        if len(stripped) < 30 and "/" not in stripped and "\\" not in stripped:
            return IntentCategory.GENERAL_QA_OR_CHAT

        return IntentCategory.AMBIGUOUS


class TokenBurnGuard:
    """Safeguards user token quota from unintentional workspace tree attachment."""

    DEFAULT_WORKSPACE_THROTTLE_THRESHOLD_TOKENS: ClassVar[int] = 2000

    @classmethod
    def evaluate_guard(
        cls,
        *,
        track: SessionScenarioTrack,
        prompt: str,
        workspace_tokens: int,
        base_prompt_tokens: int = 1500,
        auto_throttle_on_chat: bool = True,
    ) -> BurnGuardDecision:
        """Determines whether to throttle workspace context based on active track and intent."""
        # 1. Thinking / Q&A track is strictly isolated by default
        if track == SessionScenarioTrack.THINKING_QA_TRACK:
            total_with = base_prompt_tokens + workspace_tokens
            pct = (workspace_tokens / total_with) if total_with > 0 else 0.0
            return BurnGuardDecision(
                action=BurnGuardAction.PASSTHROUGH,
                detected_intent=IntentCategory.GENERAL_QA_OR_CHAT,
                workspace_stripped=True,
                estimated_tokens_saved=workspace_tokens,
                savings_percentage=pct,
                user_advisory_message=None,
            )

        # 2. Dev track: inspect intent to prevent accidental quota burning
        intent = UserIntentClassifier.classify_intent(prompt)
        if intent == IntentCategory.ENGINEERING_DEV or not auto_throttle_on_chat:
            return BurnGuardDecision(
                action=BurnGuardAction.PASSTHROUGH,
                detected_intent=intent,
                workspace_stripped=False,
                estimated_tokens_saved=0,
                savings_percentage=0.0,
                user_advisory_message=None,
            )

        # 3. Intent is General Chat or Ambiguous with huge workspace context
        if workspace_tokens >= cls.DEFAULT_WORKSPACE_THROTTLE_THRESHOLD_TOKENS:
            total_cost = base_prompt_tokens + workspace_tokens
            pct = (workspace_tokens / total_cost) if total_cost > 0 else 0.0
            advisory = (
                f"当前提问被识别为常规问答（未引用项目代码），已自动为您节流工作区工程上下文，"
                f"预计为您节省约 {workspace_tokens:,} Token ({pct:.0%})。"
            )
            return BurnGuardDecision(
                action=BurnGuardAction.THROTTLE_WORKSPACE_CONTEXT,
                detected_intent=intent,
                workspace_stripped=True,
                estimated_tokens_saved=workspace_tokens,
                savings_percentage=pct,
                user_advisory_message=advisory,
            )

        # Workspace is already negligible
        return BurnGuardDecision(
            action=BurnGuardAction.PASSTHROUGH,
            detected_intent=intent,
            workspace_stripped=False,
            estimated_tokens_saved=0,
            savings_percentage=0.0,
            user_advisory_message=None,
        )


class DualTrackSessionGuardHub:
    """Coordinates system prompt assembly respecting track boundaries and burn guards."""

    @classmethod
    def assemble_context(
        cls,
        *,
        track: SessionScenarioTrack,
        prompt: str,
        base_system_prompt: str,
        workspace_context: str,
        estimated_workspace_tokens: int,
        estimated_base_tokens: int = 1500,
        auto_throttle: bool = True,
    ) -> DualTrackContextAssembly:
        """Generates the optimal prompt assembly and emits cost-saving guard decisions."""
        decision = TokenBurnGuard.evaluate_guard(
            track=track,
            prompt=prompt,
            workspace_tokens=estimated_workspace_tokens,
            base_prompt_tokens=estimated_base_tokens,
            auto_throttle_on_chat=auto_throttle,
        )

        if decision.workspace_stripped:
            assembled = base_system_prompt.strip()
            included = False
        else:
            stripped_ws = workspace_context.strip()
            if stripped_ws:
                assembled = f"{base_system_prompt.strip()}\n\n{stripped_ws}"
                included = True
            else:
                assembled = base_system_prompt.strip()
                included = False

        return DualTrackContextAssembly(
            active_track=track,
            workspace_included=included,
            assembled_system_prompt=assembled,
            decision=decision,
        )
