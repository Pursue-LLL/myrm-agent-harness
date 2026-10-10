"""Extractor for unstructured entities, commitments, and blockers from work events.

[INPUT]
- WorkEvent objects or raw text strings from multiple sources (Feishu, DingTalk, Linear, local files).

[OUTPUT]
- ContextFabricExtractor: produces structured WorkContextEntity instances with roles and temporal anchors.

[POS]
- Entity extraction engine for Item 153 CrossSourceWorkContextFabricAndProjectEntityLinkerSuite.
"""

from __future__ import annotations

import re
import uuid

from .models import WorkContextEntity, WorkEvent

# Regex patterns for people / assignments
_PERSON_RE = re.compile(
    r"(?:(?:负责人|对接人|Owner|Assignee|指派给|由)\s*[:：]?\s*[@#]?([a-zA-Z0-9_\u4e00-\u9fa5]+)|@([a-zA-Z0-9_\u4e00-\u9fa5]+))",
    re.IGNORECASE,
)

# Regex patterns for time commitments / deadlines
_COMMITMENT_RE = re.compile(
    r"(?:将于|计划于|承诺在|截止|截止日期|Due\s*date|Due\s*by|Deadline)[:：\s]*"
    r"([0-9]{4}-[0-9]{1,2}-[0-9]{1,2}|[0-9]{1,2}月[0-9]{1,2}日|下周[一二三四五六日天]|明天|后天)",
    re.IGNORECASE,
)

# Regex patterns for blockers and risks
_BLOCKER_RE = re.compile(
    r"(?:阻塞(?:原因|点)?|卡点|阻碍|Blocker|Blocked\s*by)[:：\s]*([^\n,，;；。]+)",
    re.IGNORECASE,
)

# Regex patterns for explicit project / module tags
_EXPLICIT_TAG_RE = re.compile(
    r"(?:[#【\[]([a-zA-Z0-9_\u4e00-\u9fa5-]{2,20})[#】\]]|(?:项目|模块)[:：]\s*([a-zA-Z0-9_\u4e00-\u9fa5-]{2,20}))",
    re.IGNORECASE,
)


class ContextFabricExtractor:
    """Extracts people, commitments, blockers, and project modules from work event texts."""

    def extract_from_event(self, event: WorkEvent) -> list[WorkContextEntity]:
        """Extract all structured context entities from a single WorkEvent."""
        full_text = f"{event.title}\n{event.raw_content}"
        return self.extract_from_text(full_text)

    def extract_from_text(self, text: str) -> list[WorkContextEntity]:
        """Parse raw text and return list of WorkContextEntity instances."""
        entities: list[WorkContextEntity] = []
        seen_keys: set[tuple[str, str]] = set()

        # 1. Extract explicit project/module tags
        for match in _EXPLICIT_TAG_RE.finditer(text):
            tag_name = (match.group(1) or match.group(2) or "").strip()
            if tag_name and len(tag_name) >= 2:
                key = ("module", tag_name.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        WorkContextEntity(
                            entity_id=uuid.uuid4().hex[:8],
                            entity_type="module",
                            name=tag_name,
                            role_or_relation="referenced_tag",
                            confidence=0.9,
                            evidence_snippet=match.group(0),
                        )
                    )

        # 2. Extract people assignments
        for match in _PERSON_RE.finditer(text):
            person_name = (match.group(1) or match.group(2) or "").strip()
            if person_name and len(person_name) >= 2:
                key = ("person", person_name.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        WorkContextEntity(
                            entity_id=uuid.uuid4().hex[:8],
                            entity_type="person",
                            name=person_name,
                            role_or_relation="stakeholder",
                            confidence=0.85,
                            evidence_snippet=match.group(0),
                        )
                    )

        # 3. Extract time commitments
        for match in _COMMITMENT_RE.finditer(text):
            time_target = match.group(1).strip()
            if time_target:
                snippet = match.group(0).strip()
                key = ("commitment", snippet.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        WorkContextEntity(
                            entity_id=uuid.uuid4().hex[:8],
                            entity_type="commitment",
                            name=snippet,
                            role_or_relation="deadline",
                            temporal_anchor=time_target,
                            status="active",
                            confidence=0.88,
                            evidence_snippet=snippet,
                        )
                    )

        # 4. Extract blockers
        for match in _BLOCKER_RE.finditer(text):
            blocker_desc = match.group(1).strip()
            if blocker_desc and len(blocker_desc) >= 3:
                snippet = match.group(0).strip()
                key = ("blocker", blocker_desc.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    entities.append(
                        WorkContextEntity(
                            entity_id=uuid.uuid4().hex[:8],
                            entity_type="blocker",
                            name=blocker_desc,
                            role_or_relation="impediment",
                            status="blocked",
                            confidence=0.85,
                            evidence_snippet=snippet,
                        )
                    )

        return entities
