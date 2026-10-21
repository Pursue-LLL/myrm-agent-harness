"""Intake garbage filter guarding long-term memory against ephemeral noise.

[INPUT]
- str: raw candidate content to be ingested into profile or notes
- Optional[MemoryLayerType]: suggested target layer hint
- types: IntakeDecision, MemoryLayerType, GarbageCategory

[OUTPUT]
- MemoryIntakeGarbageFilter: deterministic heuristic filter classifying content
  as long-term knowledge or rejecting it as transient garbage.

[POS]
Intake gatekeeper implementing Hermes memory guidelines, preventing task progress,
ephemeral issue numbers, and transient error traces from polluting vector memory.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.profile_notes.types import (
    GarbageCategory,
    IntakeDecision,
    MemoryLayerType,
)

# 1. Ephemeral Task Progress Patterns
_TASK_PROGRESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:phase|step|stage)\s*\d+\s*(?:completed|finished|done|passed)", re.IGNORECASE),
    re.compile(
        r"(?:第\s*[一二三四五六七八九十\d]+\s*(?:阶段|步|节|期|周期|轮次|轮))\s*(?:已完成|完成|成功|跑通|结束)",
        re.IGNORECASE,
    ),
    re.compile(r"(?:任务|子任务|流程|测试)\s*(?:已完成|完成度\s*100%|已跑通|成功通过)", re.IGNORECASE),
    re.compile(r"(?:all\s+tests\s+passed|build\s+succeeded|deployment\s+finished)", re.IGNORECASE),
)

# 2. Ephemeral Numbers and Transient Identifiers
_EPHEMERAL_NUMBER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:\bpr|\bpull\s*request)\s*#\s*\d+\b", re.IGNORECASE),
    re.compile(r"(?:\bissue|\bticket|\bjob)\s*#\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bcommit\s+[0-9a-f]{7,40}\b", re.IGNORECASE),
    re.compile(r"\btask-[0-9a-z]{4,12}\b", re.IGNORECASE),
)

# 3. Transient Error and Debug Traceback Patterns
_TRANSIENT_ERROR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"traceback\s*\(most\s+recent\s+call\s+last\):", re.IGNORECASE),
    re.compile(r"(?:file\s+\"[^\"]+\",\s+line\s+\d+,\s+in\s+[^\n]+)", re.IGNORECASE),
    re.compile(r"(?:exception|syntaxerror|typeerror|valueerror|indexerror):\s+", re.IGNORECASE),
    re.compile(r"(?:exit\s+(?:status|code)\s+\d+)", re.IGNORECASE),
    re.compile(r"(?:killed|sigkill|sigsegv|oom\s+killed)", re.IGNORECASE),
)

# 4. Ephemeral Temporal Relative Markers (Short-term transient facts)
_TRANSIENT_TEMPORAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(?:刚才|刚刚|五分钟前|半小时前|今天下午|今天上午|昨天晚上)", re.IGNORECASE),
    re.compile(r"^(?:just\s+now|a\s+few\s+minutes\s+ago|earlier\s+today)[,\s]", re.IGNORECASE),
)

# Semantic User Preference Markers (User-level habits and personal directives)
_USER_PREFERENCE_KEYWORDS: tuple[str, ...] = (
    "prefer",
    "preference",
    "偏好",
    "习惯",
    "我的名字",
    "我叫",
    "母语",
    "native language",
    "code style",
    "coding style",
    "代码风格",
    "personal preference",
)

# Semantic Agent Working Notes / Project Conventions Markers
_AGENT_NOTE_KEYWORDS: tuple[str, ...] = (
    "architecture",
    "convention",
    "guideline",
    "规范",
    "架构",
    "设计原则",
    "项目约定",
    "trick",
    "pattern",
    "最佳实践",
    "best practice",
    "规则",
    "rule",
)


class MemoryIntakeGarbageFilter:
    """Intake filter detecting and discarding ephemeral noise before memory insertion."""

    def __init__(self, strict_mode: bool = True) -> None:
        self._strict_mode = strict_mode

    def evaluate_intake(
        self,
        content: str,
        layer_hint: MemoryLayerType | None = None,
    ) -> IntakeDecision:
        """Evaluate candidate text against noise filters and route to target memory layer.

        Args:
            content: Raw candidate memory string.
            layer_hint: Optional manual suggestion of the target layer.

        Returns:
            An IntakeDecision detailing whether content was accepted or rejected.
        """
        stripped = content.strip()
        if not stripped:
            return IntakeDecision(
                accepted=False,
                target_layer=None,
                rejected_reason="Empty content cannot be saved to memory.",
                garbage_category=None,
            )

        # 1. Ephemeral Task Progress Check
        for pattern in _TASK_PROGRESS_PATTERNS:
            if pattern.search(stripped):
                return IntakeDecision(
                    accepted=False,
                    target_layer=None,
                    rejected_reason=f"Rejected task progress milestone: matched '{pattern.pattern}'.",
                    garbage_category=GarbageCategory.TASK_PROGRESS,
                )

        # 2. Ephemeral Numbers and References Check
        for pattern in _EPHEMERAL_NUMBER_PATTERNS:
            if pattern.search(stripped):
                return IntakeDecision(
                    accepted=False,
                    target_layer=None,
                    rejected_reason=f"Rejected ephemeral reference identifier: matched '{pattern.pattern}'.",
                    garbage_category=GarbageCategory.EPHEMERAL_NUMBER,
                )

        # 3. Transient Error / Stacktrace Check
        for pattern in _TRANSIENT_ERROR_PATTERNS:
            if pattern.search(stripped):
                return IntakeDecision(
                    accepted=False,
                    target_layer=None,
                    rejected_reason="Rejected transient error stacktrace or process exit code.",
                    garbage_category=GarbageCategory.TRANSIENT_ERROR,
                )

        # 4. Ephemeral Relative Temporal Check
        for pattern in _TRANSIENT_TEMPORAL_PATTERNS:
            if pattern.search(stripped):
                return IntakeDecision(
                    accepted=False,
                    target_layer=None,
                    rejected_reason="Rejected ephemeral transient statement tied to immediate time.",
                    garbage_category=GarbageCategory.TRANSIENT_TEMPORAL,
                )

        # 5. Route to Target Layer (User vs Memory)
        target_layer = self._determine_target_layer(stripped, layer_hint)
        return IntakeDecision(
            accepted=True,
            target_layer=target_layer,
            rejected_reason=None,
            garbage_category=None,
        )

    def _determine_target_layer(
        self,
        content: str,
        layer_hint: MemoryLayerType | None,
    ) -> MemoryLayerType:
        """Determine whether content belongs to USER profile or MEMORY working notes."""
        if layer_hint is not None:
            return layer_hint

        lower = content.lower()
        # Check User profile indicators
        if any(kw in lower for kw in _USER_PREFERENCE_KEYWORDS):
            return MemoryLayerType.USER

        # Check Agent working notes indicators
        if any(kw in lower for kw in _AGENT_NOTE_KEYWORDS):
            return MemoryLayerType.MEMORY

        # Default fallback to MEMORY layer for agent-level domain facts
        return MemoryLayerType.MEMORY
