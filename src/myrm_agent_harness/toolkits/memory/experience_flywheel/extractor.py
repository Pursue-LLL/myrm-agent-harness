"""Extractor for engineering bug experiences and architectural decisions (ADR).

[INPUT]
- Execution traces, failure logs, and architectural decision records.

[OUTPUT]
- BugExperienceAndADRExtractor: transforms raw task outcomes into EngineeringExperience records.

[POS]
- Experience and ADR extraction engine for Item 154 ProjectExperienceAndADRFlywheelSuite.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from .models import EngineeringExperience, ExperienceKind

# Matches target entities like: [Entity: sqlite3], 目标模块: auth, Table: users
_ENTITY_RE = re.compile(
    r"(?:(?:模块|组件|实体|目标|Entity|Module|Table|API)[:：\s]*`?([a-zA-Z0-9_\u4e00-\u9fa5.-]+)`?|\[([a-zA-Z0-9_\u4e00-\u9fa5.-]+)\])",
    re.IGNORECASE,
)

# Matches trigger conditions: 触发条件: Python 3.13 下, When calling foo()
_TRIGGER_RE = re.compile(
    r"(?:触发条件|场景|Precondition|When|Trigger)[:：\s]*([^\n;；]+)",
    re.IGNORECASE,
)

# Matches root causes or rationales: 根因: ..., 论据: ..., Because: ...
_CAUSE_RE = re.compile(
    r"(?:根因|原因|报错原因|理由|Rationale|Root\s*Cause|Because)[:：\s]*([^\n;；]+)",
    re.IGNORECASE,
)

# Matches conventions or remedies: 解法: ..., 约定: ..., Fix: ..., Convention: ...
_REMEDY_RE = re.compile(
    r"(?:有效解法|解法|禁忌约定|约定|规范|规范做法|Fix|Remedy|Convention|Rule)[:：\s]*([^\n;；]+)",
    re.IGNORECASE,
)


class BugExperienceAndADRExtractor:
    """Extracts structured bug experiences and ADR items from task narratives."""

    def extract_from_trace(
        self,
        narrative: str,
        default_kind: ExperienceKind = ExperienceKind.BUG_EXPERIENCE,
    ) -> list[EngineeringExperience]:
        """Extract all identifiable engineering experience items from narrative text."""
        experiences: list[EngineeringExperience] = []
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")

        # Split into candidate paragraphs or bullet lines
        paragraphs = [p.strip() for p in narrative.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [narrative.strip()]

        for p in paragraphs:
            # Determine experience kind
            is_adr = bool(
                re.search(r"(?:决策|选型|ADR|架构决定|Decision|Tradeoff|设计决策)", p, re.IGNORECASE)
            )
            is_bug = bool(
                re.search(r"(?:踩坑|报错|失败|Bug|Error|Exception|死锁|冲突|卡阻)", p, re.IGNORECASE)
            )

            kind = ExperienceKind.ARCHITECTURAL_DECISION if is_adr else (
                ExperienceKind.BUG_EXPERIENCE if is_bug else default_kind
            )

            # 1. Extract target entity
            entity_match = _ENTITY_RE.search(p)
            target_entity = (
                (entity_match.group(1) or entity_match.group(2) or "").strip()
                if entity_match
                else "general_system"
            )

            # 2. Extract trigger condition
            trigger_match = _TRIGGER_RE.search(p)
            trigger_condition = trigger_match.group(1).strip() if trigger_match else "standard_execution"

            # 3. Extract root cause / rationale
            cause_match = _CAUSE_RE.search(p)
            root_cause = cause_match.group(1).strip() if cause_match else p[:120].strip()

            # 4. Extract remedy / convention
            remedy_match = _REMEDY_RE.search(p)
            if remedy_match:
                convention = remedy_match.group(1).strip()
            else:
                # If no explicit convention label, infer from last sentence or phrase
                sentences = [s.strip() for s in re.split(r"[。；;\n]", p) if s.strip()]
                convention = sentences[-1] if len(sentences) > 1 else "Follow strict verified conventions"

            exp_id = uuid.uuid4().hex[:6]
            experiences.append(
                EngineeringExperience(
                    experience_id=exp_id,
                    kind=kind,
                    target_entity=target_entity,
                    trigger_condition=trigger_condition,
                    root_cause_or_rationale=root_cause,
                    convention_or_remedy=convention,
                    created_date=today_str,
                    tags=(target_entity.lower(), kind.value),
                    confidence=0.88,
                )
            )

        return experiences
