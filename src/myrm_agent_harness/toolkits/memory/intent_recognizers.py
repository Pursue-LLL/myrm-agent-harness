"""Query intent recognition for adaptive type weighting.

Analyzes user queries to identify intent (FACT vs PREFERENCE) and dynamically
adjusts memory type weights for improved retrieval accuracy.

Zero-LLM-cost implementation using keyword matching.

[INPUT]
- (none)

[OUTPUT]
- QueryIntent: Query intent categories for adaptive type weighting.
- IntentRecognitionResult: Result of query intent recognition.
- QueryIntentRecognizer: Protocol for query intent recognition strategies.
- KeywordBasedRecognizer: Keyword-based query intent recognizer (zero LLM cost).

[POS]
Query intent recognition for adaptive type weighting.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Protocol

from myrm_agent_harness.toolkits.memory.types import MemoryType


class QueryIntent(Enum):
    """Query intent categories for adaptive type weighting."""

    FACT = "fact"
    PREFERENCE = "preference"
    GENERAL = "general"


@dataclass(frozen=True, slots=True)
class IntentRecognitionResult:
    """Result of query intent recognition.

    Attributes:
        intent: Identified query intent
        confidence: Recognition confidence (0.0-1.0)
        type_weights: Suggested memory type weights for this intent
    """

    intent: QueryIntent
    confidence: float
    type_weights: dict[MemoryType, float]


class QueryIntentRecognizer(Protocol):
    """Protocol for query intent recognition strategies.

    Allows custom implementations for different recognition approaches
    (keyword-based, LLM-based, etc.).
    """

    def recognize(self, query: str) -> IntentRecognitionResult:
        """Recognize query intent and suggest type weights.

        Args:
            query: User query string

        Returns:
            Intent recognition result with suggested type weights
        """
        ...


class KeywordBasedRecognizer:
    """Keyword-based query intent recognizer (zero LLM cost).

    Identifies intent based on keyword patterns:
    - FACT: "when", "where", "who", "said", "told", etc.
    - PREFERENCE: "prefer", "like", "favorite", "喜欢", "偏好", etc.
    - GENERAL: fallback for other queries

    Supports configurable keyword extension.
    """

    DEFAULT_FACT_KEYWORDS: ClassVar[list[str]] = [
        # English
        "when",
        "where",
        "who",
        "said",
        "told",
        "mentioned",
        "talked",
        "discussed",
        "meeting",
        "conversation",
        "last time",
        "previously",
        "remember when",
        # Chinese
        "什么时候",
        "哪里",
        "谁",
        "说过",
        "提到",
        "讨论",
        "之前",
        "上次",
    ]

    DEFAULT_PREFERENCE_KEYWORDS: ClassVar[list[str]] = [
        # English
        "prefer",
        "favorite",
        "love",
        "hate",
        "dislike",
        "wish",
        "i like",
        "i want",
        "i need",
        "my style",
        "my habit",
        # Chinese
        "喜欢",
        "偏好",
        "讨厌",
        "希望",
        "习惯",
        "风格",
        "倾向",
    ]

    def __init__(self, fact_keywords: list[str] | None = None, preference_keywords: list[str] | None = None) -> None:
        """Initialize recognizer with optional custom keywords.

        Args:
            fact_keywords: Custom fact keywords (extends defaults)
            preference_keywords: Custom preference keywords (extends defaults)
        """
        self.fact_keywords = set(self.DEFAULT_FACT_KEYWORDS)
        if fact_keywords:
            self.fact_keywords.update(fact_keywords)

        self.preference_keywords = set(self.DEFAULT_PREFERENCE_KEYWORDS)
        if preference_keywords:
            self.preference_keywords.update(preference_keywords)

    def recognize(self, query: str) -> IntentRecognitionResult:
        """Recognize intent based on keyword matching."""
        query_lower = query.lower()

        fact_matches = sum(1 for kw in self.fact_keywords if kw in query_lower)
        pref_matches = sum(1 for kw in self.preference_keywords if kw in query_lower)

        if fact_matches > pref_matches and fact_matches > 0:
            return IntentRecognitionResult(
                intent=QueryIntent.FACT, confidence=min(fact_matches / 3.0, 1.0), type_weights=self._get_fact_weights()
            )
        elif pref_matches > fact_matches and pref_matches > 0:
            return IntentRecognitionResult(
                intent=QueryIntent.PREFERENCE,
                confidence=min(pref_matches / 3.0, 1.0),
                type_weights=self._get_preference_weights(),
            )
        else:
            return IntentRecognitionResult(
                intent=QueryIntent.GENERAL, confidence=0.5, type_weights=self._get_general_weights()
            )

    def _get_fact_weights(self) -> dict[MemoryType, float]:
        """Type weights optimized for fact queries."""
        return {
            MemoryType.EPISODIC: 1.0,
            MemoryType.SEMANTIC: 0.9,
            MemoryType.CONVERSATION: 0.95,
            MemoryType.PROFILE: 0.5,
            MemoryType.PROCEDURAL: 0.7,
        }

    def _get_preference_weights(self) -> dict[MemoryType, float]:
        """Type weights optimized for preference queries."""
        return {
            MemoryType.PROFILE: 1.0,
            MemoryType.SEMANTIC: 0.7,
            MemoryType.CONVERSATION: 0.8,
            MemoryType.EPISODIC: 0.6,
            MemoryType.PROCEDURAL: 0.7,
        }

    def _get_general_weights(self) -> dict[MemoryType, float]:
        """Type weights for general queries (default balanced weights)."""
        return {
            MemoryType.PROFILE: 1.0,
            MemoryType.SEMANTIC: 1.0,
            MemoryType.EPISODIC: 0.8,
            MemoryType.CONVERSATION: 0.95,
            MemoryType.PROCEDURAL: 0.9,
        }
