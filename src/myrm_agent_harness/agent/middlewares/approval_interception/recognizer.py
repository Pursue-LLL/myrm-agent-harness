"""[INPUT]
- (none)

[OUTPUT]
- ApprovalIntent: Lightweight intent recognizer for approval texts.
- ApprovalIntentRecognizer: class — Approval Intent Recognizer

[POS]
Provides ApprovalIntent, ApprovalIntentRecognizer.
"""

import re
from enum import StrEnum


class ApprovalIntent(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVE_ALWAYS = "approve_always"
    FEEDBACK = "feedback"


class ApprovalIntentRecognizer:
    """Lightweight intent recognizer for approval texts.

    Uses regex matching to handle natural language variations (e.g. "好，你继续吧").
    If no explicit intent is matched, it's considered FEEDBACK.
    """

    # Regex patterns for intent recognition (case-insensitive)
    # Matches: "y", "yes", "ok", "同意", "确认", "继续", "好", "好的", "approve", "accept", "可以", "行", "没问题"
    # Followed by optional punctuation and trailing words like "吧", "你继续吧"
    APPROVE_PATTERN = re.compile(
        r"^(y|yes|ok|同意|确认|继续|好|好的|approve|accept|可以|行|没问题)[\s，,。\.！!]*([你]*继续[吧]*|吧)*$",
        re.IGNORECASE,
    )

    # Matches: "n", "no", "拒绝", "取消", "停止", "否", "reject", "deny", "cancel", "算了", "别弄了", "不要"
    REJECT_PATTERN = re.compile(
        r"^(n|no|拒绝|取消|停止|否|reject|deny|cancel|算了|别弄了|不要)[\s，,。\.！!]*([别]*弄了|吧)*$", re.IGNORECASE
    )

    # Matches: "always", "总是允许", "approve_always", "always_allow", "以后都允许"
    ALWAYS_PATTERN = re.compile(
        r"^(always|总是允许|approve_always|always_allow|以后都允许)[\s，,。\.！!]*(吧)*$", re.IGNORECASE
    )

    @classmethod
    def recognize(cls, text: str) -> tuple[ApprovalIntent, str | None]:
        """Recognize intent from text.

        Returns:
            Tuple of (Intent, FeedbackText).
            If intent is FEEDBACK, FeedbackText is the original text.
            Otherwise, FeedbackText is None.
        """
        if not text:
            return ApprovalIntent.FEEDBACK, text

        clean_text = text.strip()

        if cls.APPROVE_PATTERN.match(clean_text):
            return ApprovalIntent.APPROVE, None

        if cls.REJECT_PATTERN.match(clean_text):
            return ApprovalIntent.REJECT, None

        if cls.ALWAYS_PATTERN.match(clean_text):
            return ApprovalIntent.APPROVE_ALWAYS, None

        # If no exact match, treat as feedback
        return ApprovalIntent.FEEDBACK, text
