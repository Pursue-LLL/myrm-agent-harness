"""Task Goal Parser decomposing queries into structured retrieval goals.

[INPUT]
- toolkits.memory.quadruple_retrieval.models::ParsedTaskGoal, QueryIntentType (POS: Domain models)

[OUTPUT]
- TaskGoalParser: Fast-path rule and heuristic intent decomposer with edge-case fallbacks.

[POS]
Task goal parser decomposing queries into structured retrieval goals.
"""

from __future__ import annotations

import re
import uuid
from typing import ClassVar

from myrm_agent_harness.toolkits.memory.quadruple_retrieval.models import (
    ParsedTaskGoal,
    QueryIntentType,
)


class TaskGoalParser:
    """Pre-retrieval query decomposition engine extracting entities, temporal spans, and intents."""

    _TEMPORAL_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"(上周|上个月|昨天|刚才|上次|近期|最近|去年|前年|当年|202\d年|\d+月\d+日)", re.IGNORECASE),
        re.compile(r"(last\s+week|yesterday|earlier|recently|last\s+month|last\s+year|\d{4}-\d{2}-\d{2})", re.IGNORECASE),
    ]

    _PREFERENCE_KEYWORDS: ClassVar[set[str]] = {
        "偏好", "习惯", "更喜欢", "倾向", "禁忌", "不要", "beverage", "drink", "coffee", "tea",
        "prefer", "preference", "style", "mandate", "forbidden",
    }

    _PROCEDURAL_KEYWORDS: ClassVar[set[str]] = {
        "如何", "步骤", "怎么", "流程", "配置", "部署", "排查", "修复",
        "how", "step", "procedure", "pipeline", "deploy", "setup", "debug",
    }

    _EPISODIC_KEYWORDS: ClassVar[set[str]] = {
        "讨论过", "聊过", "会议", "对话", "提到", "记录", "那天", "经历",
        "discussed", "meeting", "mentioned", "conversation", "remember",
    }

    _TECHNICAL_KEYWORDS: ClassVar[set[str]] = {
        "规范", "要求", "标准", "红线", "架构", "pydantic", "fastapi", "python",
        "rule", "standard", "requirement", "schema",
    }

    def parse_query(
        self,
        query: str,
        scoped_filters: dict[str, str] | None = None,
    ) -> ParsedTaskGoal:
        """Parse natural language query into structured ParsedTaskGoal with edge-case safety."""
        goal_id = f"goal_{uuid.uuid4().hex[:8]}"
        clean_query = query.strip() if query else ""

        if not clean_query:
            return ParsedTaskGoal(
                goal_id=goal_id,
                original_query="",
                explicit_intent=QueryIntentType.GENERAL_EXPLORATION.value,
                target_entities=[],
                extracted_keywords=[],
                metadata_filters=dict(scoped_filters or {}),
                temporal_constraints=None,
                confidence=1.0,
            )

        # Enforce max length bounds to protect downstream processors
        bounded_query = clean_query[:1024]

        # Extract temporal constraints
        temporal_span: str | None = None
        for pattern in self._TEMPORAL_PATTERNS:
            match = pattern.search(bounded_query)
            if match:
                temporal_span = match.group(1)
                break

        # Extract named/quoted entities and terms
        target_entities: list[str] = self._extract_entities(bounded_query)

        # Classify intent type
        explicit_intent = self._classify_intent(bounded_query, temporal_span)

        # Extract lexical keywords
        keywords: list[str] = self._extract_keywords(bounded_query, target_entities)

        # Build initial metadata filters
        filters = dict(scoped_filters or {})
        if explicit_intent == "user_preference":
            filters.setdefault("category", "user_preference")
        elif explicit_intent == QueryIntentType.TECHNICAL_STANDARD.value:
            filters.setdefault("category", "technical_standard")

        return ParsedTaskGoal(
            goal_id=goal_id,
            original_query=clean_query,
            explicit_intent=explicit_intent,
            target_entities=target_entities,
            extracted_keywords=keywords,
            metadata_filters=filters,
            temporal_constraints=temporal_span,
            confidence=0.95,
        )

    def parse_goal(
        self,
        query: str,
        scoped_filters: dict[str, str] | None = None,
    ) -> ParsedTaskGoal:
        """Alias for parse_query for backwards compatibility."""
        return self.parse_query(query, scoped_filters)

    def _extract_entities(self, text: str) -> list[str]:
        """Extract explicit quoted tokens, CamelCase terms, and significant identifiers."""
        entities: list[str] = []

        # 1. Quoted terms: "..." or '...' or 「...」
        quoted = re.findall(r'["\'「]([^"\'」]+)["\'」]', text)
        entities.extend([q.strip() for q in quoted if len(q.strip()) > 1])

        # 2. Identifiers with underscores, dots, or camelCase
        identifiers = re.findall(
            r"\b[A-Za-z0-9_]{2,}(?:\.[A-Za-z0-9_]+)+\b|\b[A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b",
            text,
        )
        entities.extend(identifiers)

        # 3. Capitalized or key domain nouns (e.g. Pydantic, FastAPI, Redis)
        tech_words = re.findall(r"\b[A-Z][A-Za-z0-9_]{1,}\b", text)
        entities.extend(tech_words)

        # 4. Fallback: extract prominent segments if no structured entity found
        if not entities:
            # Split by punctuation, spaces, and common Chinese connective particles
            segments = re.split(r"[，。！？,\.!?\s]+|关于|讨论|检索|查询|与|和|及", text)
            for seg in segments:
                s_strip = seg.strip()
                if len(s_strip) >= 2 and not self._is_stopword(s_strip):
                    entities.append(s_strip)
                # Also extract 2 to 4 char Chinese n-grams
                c_words = re.findall(r"[\u4e00-\u9fa5]{2,4}", s_strip)
                for cw in c_words:
                    if not self._is_stopword(cw):
                        entities.append(cw)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped: list[str] = []
        for e in entities:
            norm = e.lower()
            if norm not in seen and len(norm) > 1:
                seen.add(norm)
                deduped.append(e)

        return deduped

    def _extract_keywords(self, text: str, entities: list[str]) -> list[str]:
        """Extract lexical keyword tokens for BM25 and lexical channels."""
        # Extract both alphanumeric tokens and Chinese multi-character words
        raw_tokens = re.findall(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fa5]{2,4}", text)
        keywords: list[str] = []
        seen: set[str] = {e.lower() for e in entities}
        keywords.extend(entities)

        for tok in raw_tokens:
            low = tok.lower()
            if len(tok) >= 2 and not self._is_stopword(tok) and low not in seen:
                seen.add(low)
                keywords.append(tok)

        return keywords

    def _classify_intent(
        self,
        text: str,
        temporal_span: str | None,
    ) -> str:
        """Heuristically infer retrieval intent category."""
        lower_text = text.lower()

        # Episodic matching (explicit temporal constraint takes highest priority)
        if temporal_span is not None or any(kw in lower_text for kw in self._EPISODIC_KEYWORDS):
            return QueryIntentType.EPISODIC.value

        # Preference matching
        if any(kw in lower_text for kw in self._PREFERENCE_KEYWORDS):
            if "用户" in lower_text or "user" in lower_text:
                return "user_preference"
            return QueryIntentType.PREFERENCE.value

        # Technical standard matching
        if any(kw in lower_text for kw in self._TECHNICAL_KEYWORDS):
            return QueryIntentType.TECHNICAL_STANDARD.value

        # Procedural matching
        if any(kw in lower_text for kw in self._PROCEDURAL_KEYWORDS):
            return QueryIntentType.PROCEDURAL.value

        # Factual query
        if any(kw in lower_text for kw in {"是什么", "参数", "定义", "what", "definition", "schema"}):
            return QueryIntentType.FACTUAL.value

        return QueryIntentType.GENERAL_EXPLORATION.value

    @staticmethod
    def _is_stopword(word: str) -> bool:
        """Filter out generic conversational noise."""
        stopwords = {
            "关于", "讨论", "上周", "昨天", "一下", "请问", "我们", "你们",
            "这个", "那个", "怎么", "什么", "因为", "所以", "如果", "查一下", "帮我",
            "the", "and", "about", "what", "with", "from", "that", "this",
        }
        return word.strip().lower() in stopwords
