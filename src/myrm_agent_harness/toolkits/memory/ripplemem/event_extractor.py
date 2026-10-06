"""Normalized event unit extractor for RippleMem architecture.

[INPUT]
- NormalizedEventUnit and models from .models.
- Standard library modules (re, datetime, uuid, logging).

[OUTPUT]
- NormalizedEventExtractor: Parser transforming raw utterances into m=(r, v, p, l, t, c).

[POS]
Extracts atomic self-contained event units with pronoun resolution,
temporal anchoring, and typed clue slot parsing for sparse graph population.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.ripplemem.models import NormalizedEventUnit

logger = logging.getLogger(__name__)

# Common relative temporal markers mapped to day offsets
_RELATIVE_TEMPORAL_OFFSETS: dict[str, int] = {
    "今天": 0,
    "今日": 0,
    "today": 0,
    "昨天": -1,
    "昨日": -1,
    "yesterday": -1,
    "前天": -2,
    "前日": -2,
    "明天": 1,
    "明日": 1,
    "tomorrow": 1,
    "后天": 2,
    "后日": 2,
    "上周": -7,
    "last week": -7,
    "上个月": -30,
    "last month": -30,
    "两周前": -14,
    "two weeks ago": -14,
}

_PRONOUNS: set[str] = {
    "他",
    "她",
    "它",
    "他们",
    "她们",
    "它们",
    "he",
    "she",
    "it",
    "they",
    "him",
    "her",
    "them",
}


_NON_PERSON_SUBSTRINGS: tuple[str, ...] = (
    "码头",
    "海鲜",
    "蟹",
    "一起",
    "店",
    "坊",
    "方案",
    "网关",
    "火锅",
    "餐厅",
    "天气",
    "北京",
    "上海",
)


class NormalizedEventExtractor:
    """Extracts and normalizes raw text utterances into atomic event units."""

    def __init__(self, *, default_location: str = "") -> None:
        self._default_location = default_location

    def extract_event(
        self,
        text: str,
        *,
        session_id: str = "",
        reference_time: datetime | None = None,
        context_speaker: str = "",
        explicit_participants: list[str] | None = None,
        explicit_locations: list[str] | None = None,
        explicit_concepts: list[str] | None = None,
        embedding: list[float] | None = None,
    ) -> NormalizedEventUnit:
        """Parse text into a normalized event unit with entity and temporal grounding."""
        ref_dt = reference_time or datetime.now(UTC)
        canonical_text, participants, locations, concepts, time_span = self._normalize_content(
            text,
            reference_time=ref_dt,
            context_speaker=context_speaker,
        )

        if explicit_participants:
            participants = sorted(set(participants).union(explicit_participants))
        if explicit_locations:
            locations = sorted(set(locations).union(explicit_locations))
        if explicit_concepts:
            concepts = sorted(set(concepts).union(explicit_concepts))

        event_id = f"evt_{uuid.uuid4().hex[:12]}"

        return NormalizedEventUnit(
            id=event_id,
            representation=canonical_text,
            embedding=embedding or [],
            participants=participants,
            locations=locations,
            time_span=time_span,
            concepts=concepts,
            raw_text=text,
            session_id=session_id,
            created_at=ref_dt,
        )

    def _normalize_content(
        self,
        text: str,
        *,
        reference_time: datetime,
        context_speaker: str,
    ) -> tuple[str, list[str], list[str], list[str], str]:
        """Resolve pronouns, anchor relative times, and extract typed clue entities."""
        cleaned = text.strip()
        time_span = self._extract_and_anchor_time(cleaned, reference_time)
        resolved_text, participants = self._resolve_pronouns_and_actors(
            cleaned,
            context_speaker=context_speaker,
        )
        locations = self._extract_locations(resolved_text)
        concepts = self._extract_concepts(resolved_text)

        return resolved_text, participants, locations, concepts, time_span

    def _extract_and_anchor_time(self, text: str, ref_time: datetime) -> str:
        """Anchor relative temporal mentions into ISO date representations."""
        for pattern, day_delta in _RELATIVE_TEMPORAL_OFFSETS.items():
            if pattern in text.lower():
                target_date = ref_time + timedelta(days=day_delta)
                return target_date.strftime("%Y-%m-%d")

        # Absolute ISO date regex detection (YYYY-MM-DD)
        iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
        if iso_match:
            return iso_match.group(0)

        # Year-month regex (YYYY年MM月 or YYYY/MM)
        ym_match = re.search(r"(\d{4})[年/-](\d{1,2})(?:[月/-](\d{1,2}))?", text)
        if ym_match:
            year, month, day = (
                ym_match.group(1),
                ym_match.group(2).zfill(2),
                (ym_match.group(3) or "01").zfill(2),
            )
            return f"{year}-{month}-{day}"

        return ref_time.strftime("%Y-%m-%d")

    def _resolve_pronouns_and_actors(
        self,
        text: str,
        *,
        context_speaker: str,
    ) -> tuple[str, list[str]]:
        """Resolve first-person pronouns and extract explicit actor names."""
        result_text = text
        participants: set[str] = set()

        if context_speaker:
            # Replace first-person references with speaker identity
            first_person_patterns = [r"\b我\b", r"\b俺\b", r"\b本人\b", r"\bme\b", r"\bi\b", r"\bmy\b"]
            for pattern in first_person_patterns:
                result_text = re.sub(pattern, context_speaker, result_text, flags=re.IGNORECASE)
            participants.add(context_speaker)

        # Extract explicit capitalized names or common Chinese naming patterns (2~3 chars)
        cn_name_matches = re.findall(r"(?:小|老|王|李|张|刘|陈|赵|周)[一-龥]{1,2}", result_text)
        for name in cn_name_matches:
            # Clean trailing particles like "一起", "在", "和"
            clean_name = re.sub(r"[在和与的一]$", "", name).strip()
            if len(clean_name) >= 2 and not any(sub in clean_name for sub in _NON_PERSON_SUBSTRINGS):
                participants.add(clean_name)

        en_name_matches = re.findall(r"\b[A-Z][a-z]{2,15}\b", result_text)
        common_words = {"The", "And", "For", "With", "Today", "Yesterday", "Notice"}
        for name in en_name_matches:
            if name not in common_words:
                participants.add(name)

        return result_text, sorted(participants)

    def _extract_locations(self, text: str) -> list[str]:
        """Extract physical or domain locations from text."""
        locations: set[str] = set()
        if self._default_location:
            locations.add(self._default_location)

        loc_patterns = [
            r"([一-龥]{2,10}(?:店|坊|厅|馆|所|室|院|厦|园|海鲜|火锅|餐厅|网关))",
            r"\b(?:Beijing|Shanghai|Wangjing|Office|Gateway)\b",
        ]
        for pattern in loc_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if len(match.strip()) >= 2:
                    locations.add(match.strip())

        return sorted(locations)

    def _extract_concepts(self, text: str) -> list[str]:
        """Extract domain concepts, tech terms, and constraints from text."""
        concepts: set[str] = set()
        keywords = [
            "过敏",
            "忌口",
            "海鲜",
            "火锅",
            "休克",
            "急诊",
            "TLS",
            "API",
            "网关",
            "HTTP/3",
            "兼容",
            "升级",
            "冲突",
            "禁用",
            "推荐",
            "聚餐",
            "预算",
        ]
        for kw in keywords:
            if kw.lower() in text.lower():
                concepts.add(kw)

        return sorted(concepts)
