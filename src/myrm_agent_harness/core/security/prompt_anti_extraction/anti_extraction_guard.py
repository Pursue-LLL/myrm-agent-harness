"""Anti-Extraction Semantic Guard and Outbound Prompt Scrubber.

Detects probing attempts designed to reverse-engineer or extract system prompts,
and scrubs sensitive directive fragments and canary tokens before outbound dispatch.
"""

from __future__ import annotations

import logging
import re

from myrm_agent_harness.core.security.prompt_anti_extraction.types import (
    ExtractionDetectionResult,
)

logger = logging.getLogger(__name__)

SAFE_FALLBACK_DECLARATION: str = (
    "抱歉，作为安全企业级智能助手，我无法透露或复述内部系统提示词与前置配置。"
    "请告诉我您的具体工作需求，我将竭诚为您协助。"
)

_EXTRACTION_PROBE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(repeat|show|print|output|display|reveal|quote)\s+(your\s+)?(full\s+|system\s+|initial\s+|base\s+)*(prompt|instructions|rules|configuration|directives)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(what\s+are\s+your\s+(initial\s+)?instructions|what\s+is\s+your\s+system\s+prompt)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(format|output|reveal|show|print)\s+(your\s+)?(initial\s+)?(instructions|prompt|rules|directives)\s+(as|in)\s+(yaml|json|markdown|python|xml)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(复述|输出|打印|告诉我|透露|展示|写出).*(系统提示词|前置设定|所有指令|Prompt|初始规则|内部配置)",
        re.IGNORECASE,
    ),
    re.compile(
        r"从第一句开始(复述|输出|打印)|从头到尾(复述|输出)",
        re.IGNORECASE,
    ),
)


class AntiExtractionSemanticGuard:
    """Semantic guard defending intellectual property prompts against reverse-extraction probes."""

    def detect_extraction_probe(self, user_text: str) -> ExtractionDetectionResult:
        """Scan user query for extraction probe patterns."""
        cleaned = user_text.strip()
        if not cleaned:
            return ExtractionDetectionResult(
                is_extraction_attempt=False,
                matched_pattern=None,
                safe_fallback_response="",
            )

        for pattern in _EXTRACTION_PROBE_PATTERNS:
            match = pattern.search(cleaned)
            if match:
                matched_str = match.group(0)
                logger.warning("Prompt extraction probe intercepted: '%s'", matched_str)
                return ExtractionDetectionResult(
                    is_extraction_attempt=True,
                    matched_pattern=matched_str,
                    safe_fallback_response=SAFE_FALLBACK_DECLARATION,
                )

        return ExtractionDetectionResult(
            is_extraction_attempt=False,
            matched_pattern=None,
            safe_fallback_response="",
        )

    def scrub_outbound_text(
        self,
        text: str,
        canary_token: str | None = None,
        confidential_snippets: list[str] | None = None,
    ) -> str:
        """Scrub canary token and private directive snippets from outbound text."""
        result = text
        if canary_token and canary_token in result:
            result = result.replace(canary_token, "[REDACTED_CANARY_TOKEN]")

        if confidential_snippets:
            for snippet in confidential_snippets:
                stripped = snippet.strip()
                if stripped and stripped in result:
                    result = result.replace(stripped, "[PROTECTED_SYSTEM_DIRECTIVE]")

        return result
