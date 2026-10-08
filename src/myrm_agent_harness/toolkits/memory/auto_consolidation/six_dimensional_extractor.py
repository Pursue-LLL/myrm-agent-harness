"""Six-dimensional structured memory extractor for auto-consolidation.

[INPUT]
- collections.abc.Sequence, collections.abc.Mapping
- datetime (datetime, timezone)
- re, hashlib
- auto_consolidation.models::SixDimensionalMemoryArtifact

[OUTPUT]
- SixDimensionalMemoryExtractor: Deterministic, high-yield structured distillation extractor.

[POS]
Distillation engine converting session dialogues, workspace state, and tool metrics into
six-dimensional structured long-term memory assets (Item 123).
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.auto_consolidation.models import (
    SixDimensionalMemoryArtifact,
)

_PREFERENCE_TRIGGERS = (
    "prefer", "always", "never", "require", "like", "rule", "must",
    "forbid", "strictly", "ensure", "avoid", "demand", "disallow",
    "偏好", "喜欢", "禁止", "必须", "永远", "规范", "严禁", "风格",
)
_LESSON_TRIGGERS = (
    "error", "failed", "failure", "bug", "exception", "fix", "trap", "warn",
    "报错", "失败", "修复", "问题", "避坑", "教训", "反思", "原因",
)
_KNOWLEDGE_TRIGGERS = (
    "architecture", "pattern", "design", "algorithm", "solution", "framework",
    "架构", "设计", "算法", "方案", "模型", "机制", "原理", "协议",
)


class SixDimensionalMemoryExtractor:
    """Extracts structured, multi-faceted engineering memory from session transcripts."""

    def extract(
        self,
        session_id: str,
        messages: Sequence[Mapping[str, str]],
        working_directory: str = "",
        tool_call_records: Sequence[str] | None = None,
        token_cost: int = 0,
    ) -> SixDimensionalMemoryArtifact:
        """Extract a structured six-dimensional memory artifact from conversation data.

        Dimensions:
        1. Working directory context
        2. Key technical topics
        3. User preferences & styling constraints
        4. Reusable domain & architectural knowledge
        5. Failure postmortems & debugging lessons
        6. Tool calling behavioral patterns
        """
        norm_working_dir = working_directory.strip() or "/workspace"
        created_at = datetime.now(UTC).isoformat()

        all_texts: list[str] = [m.get("content", "") for m in messages if m.get("content")]
        user_texts: list[str] = [
            m.get("content", "") for m in messages if m.get("role") == "user" and m.get("content")
        ]
        combined_text = "\n".join(all_texts)

        # 1. Key topics
        key_topics = self._extract_key_topics(combined_text)

        # 2. User preferences
        user_preferences = self._extract_preferences(user_texts)

        # 3. Reusable domain knowledge
        reusable_knowledge = self._extract_domain_knowledge(all_texts)

        # 4. Failure lessons
        failure_lessons = self._extract_failure_lessons(all_texts)

        # 5. Tool calling patterns
        tool_patterns = self._extract_tool_patterns(tool_call_records or [])

        # 6. Artifact digest & ID
        digest = self._build_summary_digest(
            working_dir=norm_working_dir,
            topics=key_topics,
            prefs=user_preferences,
            knowledge=reusable_knowledge,
            lessons=failure_lessons,
            patterns=tool_patterns,
        )

        id_seed = f"{session_id}:{norm_working_dir}:{created_at}"
        artifact_id = f"art-6d-{hashlib.sha256(id_seed.encode('utf-8')).hexdigest()[:16]}"

        return SixDimensionalMemoryArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            created_at_iso=created_at,
            working_directory=norm_working_dir,
            key_topics=key_topics,
            user_preferences=user_preferences,
            reusable_domain_knowledge=reusable_knowledge,
            failure_lessons=failure_lessons,
            tool_calling_patterns=tool_patterns,
            token_cost=token_cost,
            summary_digest=digest,
        )

    def _extract_key_topics(self, text: str) -> list[str]:
        words = re.findall(r"\b[A-Za-z0-9_]{3,25}\b", text)
        stop_words = {
            "the", "and", "that", "this", "with", "from", "for", "have", "not",
            "are", "was", "will", "can", "should", "could", "true", "false",
            "none", "self", "args", "kwargs", "return", "class", "def", "when",
            "our", "all", "project", "always", "never", "allow", "any", "types",
        }
        filtered = [w.lower() for w in words if w.lower() not in stop_words]
        counts = Counter(filtered)
        if not counts:
            return []
        max_count = max(counts.values()) if counts else 0
        min_freq = 2 if max_count >= 2 else 1
        return [word for word, count in counts.most_common(8) if count >= min_freq]

    def _extract_preferences(self, user_texts: Sequence[str]) -> list[str]:
        candidates: list[str] = []
        for text in user_texts:
            lines = text.splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                lower = stripped.lower()
                if any(trigger in lower for trigger in _PREFERENCE_TRIGGERS):
                    clean = re.sub(r"^[>\-\*\d\.\s]+", "", stripped)
                    if 8 <= len(clean) <= 120 and clean not in candidates:
                        candidates.append(clean)
        return candidates[:6]

    def _extract_domain_knowledge(self, all_texts: Sequence[str]) -> list[str]:
        knowledge_entries: list[str] = []
        for text in all_texts:
            lines = text.splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                lower = stripped.lower()
                if any(trigger in lower for trigger in _KNOWLEDGE_TRIGGERS):
                    clean = re.sub(r"^[>\-\*\d\.\s]+", "", stripped)
                    if 12 <= len(clean) <= 160 and clean not in knowledge_entries:
                        knowledge_entries.append(clean)
        return knowledge_entries[:6]

    def _extract_failure_lessons(self, all_texts: Sequence[str]) -> list[str]:
        lessons: list[str] = []
        for text in all_texts:
            lines = text.splitlines()
            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue
                lower = stripped.lower()
                if any(trigger in lower for trigger in _LESSON_TRIGGERS):
                    clean = re.sub(r"^[>\-\*\d\.\s]+", "", stripped)
                    if 10 <= len(clean) <= 140 and clean not in lessons:
                        lessons.append(clean)
        return lessons[:6]

    def _extract_tool_patterns(self, tool_records: Sequence[str]) -> list[str]:
        if not tool_records:
            return ["No dedicated tool telemetry detected for this session."]
        counts = Counter(tool_records)
        return [
            f"{tool_name}: invoked {count} time(s)"
            for tool_name, count in counts.most_common(5)
        ]

    def _build_summary_digest(
        self,
        working_dir: str,
        topics: list[str],
        prefs: list[str],
        knowledge: list[str],
        lessons: list[str],
        patterns: list[str],
    ) -> str:
        parts: list[str] = [f"Workspace: {working_dir}."]
        if topics:
            parts.append(f"Key Topics: {', '.join(topics[:4])}.")
        if prefs:
            parts.append(f"User Preferences: {len(prefs)} rule(s) preserved.")
        if knowledge:
            parts.append(f"Domain Insights: {len(knowledge)} architectural entry(ies).")
        if lessons:
            parts.append(f"Traps Avoided: {len(lessons)} postmortem lesson(s).")
        if patterns:
            parts.append(f"Tool Usage: {patterns[0]}.")
        return " ".join(parts)
