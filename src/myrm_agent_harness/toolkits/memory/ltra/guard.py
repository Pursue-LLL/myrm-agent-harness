"""Commercial confidentiality and sensitive privacy guard for LTRA memory.

[POS]
随身感知会议与现场录音机密防护门禁。检测商业敏感底价、内部报价、
金融卡号及隐私敏感口癖，实施物理隔离或安全红线阻断。

[INPUT]
- 会话转写文本与待入库事实陈述

[OUTPUT]
- SensitiveAudioFactGuard: 商业机密与隐私敏感识别及脱敏守卫
"""

from __future__ import annotations

import re


class SensitiveAudioFactGuard:
    """Detects commercial confidentiality and sensitive private information in speech facts."""

    # High-risk commercial secrets and financial sensitivity tokens
    _COMMERCIAL_SECRET_PATTERNS = (
        re.compile(r"(?:底价|标底|内部折扣|最低报价|成本价|毛利率)\s*(?:不能低于|至少|是|为)?\s*[\d,]+(?:\.\d+)?\s*(?:万|元|块|%|percent)?", re.IGNORECASE),
        re.compile(r"(?:千万别外传|内部机密|绝密|不能让对方知道|私下告诉你)", re.IGNORECASE),
        re.compile(r"(?:api[-_]?key|secret[-_]?token|bearer\s+[a-zA-Z0-9_\-\.]{16,})", re.IGNORECASE),
    )

    # Personal identifiable information patterns
    _PII_PATTERNS = (
        re.compile(r"\b\d{17}[\dXx]\b"),  # 18-digit National ID
        re.compile(r"\b62\d{14,17}\b"),    # Bank card starting with 62
    )

    @classmethod
    def evaluate_confidentiality(cls, text: str) -> tuple[bool, list[str]]:
        """Evaluate text and return (is_confidential, detected_risk_reasons)."""
        reasons: list[str] = []

        for pattern in cls._COMMERCIAL_SECRET_PATTERNS:
            if pattern.search(text):
                reasons.append("Commercial Pricing or Secret Disclosure")
                break

        for pattern in cls._PII_PATTERNS:
            if pattern.search(text):
                reasons.append("PII Identification Number or Financial Card")
                break

        return (len(reasons) > 0, reasons)

    @classmethod
    def sanitize_for_public_log(cls, text: str) -> str:
        """Mask sensitive pricing and credentials for non-confidential logs."""
        sanitized = text
        for pattern in cls._COMMERCIAL_SECRET_PATTERNS:
            sanitized = pattern.sub("[COMMERCIAL_CONFIDENTIAL_REDACTED]", sanitized)
        for pattern in cls._PII_PATTERNS:
            sanitized = pattern.sub("[PII_REDACTED]", sanitized)
        return sanitized
