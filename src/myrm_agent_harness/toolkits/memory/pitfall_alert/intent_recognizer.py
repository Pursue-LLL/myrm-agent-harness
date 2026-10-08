"""Shadow decision intent recognizer for proactive pitfall warnings.

[POS]
Lightweight, sub-millisecond deterministic intent sniffing engine distinguishing
exploratory inquiries from high-stakes technical commitments without extra LLM overhead.

[INPUT]
- re, uuid
- .models (DecisionIntent, DecisionIntentLevel)

[OUTPUT]
- ShadowDecisionIntentRecognizer
"""

from __future__ import annotations

import re
import uuid

from myrm_agent_harness.toolkits.memory.pitfall_alert.models import (
    DecisionIntent,
    DecisionIntentLevel,
)

# Decision action patterns indicating active migration or architectural choice
_COMMITMENT_PATTERNS = [
    re.compile(r"(?i)(准备|打算|计划|决定|换成|改用|切换到|重构成|选用|引入|移除|禁用)\s*([a-zA-Z0-9_\u4e00-\u9fa5\-]+)"),
    re.compile(r"(?i)\b(replace|migrate\s+to|switch\s+to|refactor\s+to|adopt|disable|remove)\s+([a-zA-Z0-9_\-]+)"),
    re.compile(r"(?i)从\s*([a-zA-Z0-9_\u4e00-\u9fa5\-]+)\s*(改到|换成|迁到)\s*([a-zA-Z0-9_\u4e00-\u9fa5\-]+)"),
]

# Inquiry patterns indicating harmless exploratory questions
_INQUIRY_PATTERNS = [
    re.compile(r"(?i)(如何看待|怎么看|介绍一下|区别是啥|哪个更好|优缺点|什么是)"),
    re.compile(r"(?i)\b(what\s+is|how\s+about|pros\s+and\s+cons|compare|difference\s+between)\b"),
    re.compile(r"[?？]$"),
]

# High-frequency engineering subjects prone to historical postmortems
_TECH_SUBJECT_KEYWORDS = [
    "redis", "sqlite", "postgresql", "mysql", "mongodb", "mongo", "kafka", "rabbitmq", "celery",
    "elasticsearch", "es", "clickhouse", "tidb", "docker", "k8s",
    "分布式锁", "锁", "wal", "sqlalchemy", "tortoise", "fastapi", "django",
    "微服务", "单体", "缓存", "分库分表", "jwt", "oauth", "cors", "grpc",
    "goroutine", "asyncio", "multiprocessing", "threadpool", "nogil",
]


_ACTION_WORDS = {"准备", "打算", "计划", "决定", "换成", "改用", "切换到", "重构成", "选用", "引入", "移除", "禁用"}


class ShadowDecisionIntentRecognizer:
    """Detects architectural choice commitments in user input within <1ms."""

    def __init__(self, confidence_threshold: float = 0.70) -> None:
        self._confidence_threshold = confidence_threshold

    def evaluate(self, text: str) -> DecisionIntent | None:
        """Scan input text to determine whether a decision commitment is taking place."""
        stripped = text.strip()
        if len(stripped) < 4:
            return None

        # 1. Check if input is predominantly an inquiry
        is_inquiry = any(p.search(stripped) for p in _INQUIRY_PATTERNS)

        # 2. Match commitment patterns
        matched_action = ""
        matched_subject = ""
        matched_solution = ""

        for pattern in _COMMITMENT_PATTERNS:
            match = pattern.search(stripped)
            if match:
                groups = match.groups()
                if len(groups) >= 2:
                    matched_action = groups[0]
                    matched_subject = groups[1]
                if len(groups) >= 3:
                    matched_solution = groups[2]
                break

        if matched_subject in _ACTION_WORDS:
            matched_subject = ""

        # 3. Check technical subject presence
        found_subjects = [kw for kw in _TECH_SUBJECT_KEYWORDS if kw in stripped.lower()]
        if found_subjects:
            matched_subject = found_subjects[0]

        if not matched_action and not matched_subject:
            return None

        # Calculate confidence & classify level
        confidence = 0.50
        if matched_action:
            confidence += 0.25
        if matched_subject:
            confidence += 0.20
        if is_inquiry:
            confidence -= 0.30

        confidence = max(0.10, min(1.0, confidence))
        level = (
            DecisionIntentLevel.COMMITMENT
            if (not is_inquiry and confidence >= self._confidence_threshold)
            else DecisionIntentLevel.INQUIRY
        )

        return DecisionIntent(
            intent_id=f"intent-{uuid.uuid4().hex[:8]}",
            level=level,
            action=matched_action or "consider",
            target_subject=matched_subject or (found_subjects[0] if found_subjects else "system"),
            proposed_solution=matched_solution or matched_subject,
            confidence=round(confidence, 2),
            raw_query=stripped,
        )
