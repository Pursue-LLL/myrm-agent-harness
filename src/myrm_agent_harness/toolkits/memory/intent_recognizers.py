"""Query intent recognition and sub-graph routing engine.

Analyzes user queries to identify domain intents (ACTION_GUIDANCE, EPISODIC_CAUSAL,
KNOWLEDGE_FACT, USER_PROFILE, GENERAL) and dynamically routes to dedicated memory
types and topological sub-graphs (procedural, causal, knowledge).

Pure-deterministic, zero-LLM-cost implementation using hierarchical pattern matching
and fast feature extraction (<0.2ms latency).

[INPUT]
- query: str (raw user input)

[OUTPUT]
- QueryIntent: Semantic intent classification enum.
- IntentRoutingDecision: Structured routing decision for channel pruning and sub-graph traversal.
- QueryIntentRecognizer: Strategy protocol for query intent analysis.
- DeterministicIntentRouter: Production-grade deterministic router with threshold gating.
- KeywordBasedRecognizer: Backward-compatible adapter alias.

[POS]
Memory intent recognition and sub-graph routing for adaptive channel pruning and topological retrieval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Literal, Protocol

from myrm_agent_harness.toolkits.memory.types import MemoryType


class QueryIntent(Enum):
    """Query intent categories for adaptive channel routing and type weighting."""

    ACTION_GUIDANCE = "action_guidance"  # Procedural rules, troubleshooting, command syntax
    EPISODIC_CAUSAL = "episodic_causal"  # Historical decisions, timelines, causality, past events
    KNOWLEDGE_FACT = "knowledge_fact"  # Conceptual knowledge, definitions, documentation
    USER_PROFILE = "user_profile"  # Preferences, personal habits, identity, style
    GENERAL = "general"  # Fallback broad dialogue without dominant intent


@dataclass(frozen=True, slots=True)
class IntentRoutingDecision:
    """Structured routing decision for memory retrieval.

    Attributes:
        intent: Identified semantic query intent.
        confidence: Recognition confidence score (0.0 to 1.0).
        target_types: Primary memory types recommended for retrieval.
        target_subgraphs: Topological sub-graph domains (e.g. 'procedural', 'causal', 'knowledge').
        type_weights: Suggested RRF fusion weights for each memory type.
        routing_mode: Channel dispatch mode ('pruned', 'adaptive_weighted', 'broadcast').
    """

    intent: QueryIntent
    confidence: float
    target_types: list[MemoryType]
    target_subgraphs: list[str]
    type_weights: dict[MemoryType, float]
    routing_mode: Literal["pruned", "adaptive_weighted", "broadcast"]


# Compatibility alias for legacy callers
IntentRecognitionResult = IntentRoutingDecision


class QueryIntentRecognizer(Protocol):
    """Protocol for query intent recognition and routing strategies."""

    def recognize(self, query: str) -> IntentRoutingDecision:
        """Recognize query intent and calculate routing decision.

        Args:
            query: User query string.

        Returns:
            IntentRoutingDecision containing target channels, subgraphs, and weights.
        """
        ...


class DeterministicIntentRouter:
    """Production-grade deterministic query intent router (zero LLM cost).

    Features:
    - Zero runtime overhead (<0.2ms per query).
    - Front-truncated regex/token scanning to prevent ReDoS on long inputs.
    - Confidence-based channel pruning gating (pruned when confidence >= 0.85).
    - Topological sub-graph targeting for recursive SQLite graph traversal.
    """

    HIGH_CONFIDENCE_THRESHOLD: ClassVar[float] = 0.85
    MODERATE_CONFIDENCE_THRESHOLD: ClassVar[float] = 0.50
    MAX_QUERY_SCAN_LENGTH: ClassVar[int] = 300

    # Pattern definitions for ACTION_GUIDANCE (procedural rules & troubleshooting)
    ACTION_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"(?:报错|错误|异常|失败|怎么解决|如何解决|怎么搞|怎么配|如何构建|打包失败|编译失败|规范说明|规约要求|命令用法|参数怎么传|排错|避坑|修复|deploy|build|error|exception|fail|how to|fix|troubleshoot)",
            re.IGNORECASE,
        ),
        re.compile(
            r"(?:cannot find|undefined|not found|syntax error|type error|exit code|traceback)",
            re.IGNORECASE,
        ),
    ]

    # Pattern definitions for EPISODIC_CAUSAL (events, timelines & causal rationale)
    CAUSAL_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"(?:为什么决定|为何选择|什么时候|上次|之前|上周|昨天|历史|当时|讨论过|说过|会议|决定|因果|why did we|last time|previously|remember when|decided|meeting|discussed)",
            re.IGNORECASE,
        ),
    ]

    # Pattern definitions for USER_PROFILE (preferences, habits, style)
    PROFILE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"(?:我的习惯|我的偏好|我喜欢|我讨厌|希望你|默认使用|我的项目|我的配置|prefer|favorite|love|dislike|i like|i want|my habit|my style|my configuration)",
            re.IGNORECASE,
        ),
    ]

    # Pattern definitions for KNOWLEDGE_FACT (concepts, definitions, architecture)
    KNOWLEDGE_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"(?:什么是|解释一下|概念|定义|架构|协议|规范说明|接口|what is|explain|define|concept|architecture|specification|interface|schema)",
            re.IGNORECASE,
        ),
    ]

    def recognize(self, query: str) -> IntentRoutingDecision:
        """Analyze query and compute deterministic routing decision."""
        if not query or not query.strip():
            return self._build_general_decision(confidence=0.0)

        # Slice query head to prevent regex catastrophe on massive code snippets
        scan_text = query.strip()[: self.MAX_QUERY_SCAN_LENGTH].lower()

        action_score = self._match_score(scan_text, self.ACTION_PATTERNS)
        causal_score = self._match_score(scan_text, self.CAUSAL_PATTERNS)
        profile_score = self._match_score(scan_text, self.PROFILE_PATTERNS, specificity_boost=0.15)
        knowledge_score = self._match_score(scan_text, self.KNOWLEDGE_PATTERNS)

        scores: list[tuple[QueryIntent, float]] = [
            (QueryIntent.ACTION_GUIDANCE, action_score),
            (QueryIntent.EPISODIC_CAUSAL, causal_score),
            (QueryIntent.USER_PROFILE, profile_score),
            (QueryIntent.KNOWLEDGE_FACT, knowledge_score),
        ]
        scores.sort(key=lambda x: x[1], reverse=True)
        top_intent, top_score = scores[0]

        if top_score < self.MODERATE_CONFIDENCE_THRESHOLD:
            return self._build_general_decision(confidence=top_score)

        mode: Literal["pruned", "adaptive_weighted", "broadcast"] = (
            "pruned" if top_score >= self.HIGH_CONFIDENCE_THRESHOLD else "adaptive_weighted"
        )

        if top_intent == QueryIntent.ACTION_GUIDANCE:
            return IntentRoutingDecision(
                intent=QueryIntent.ACTION_GUIDANCE,
                confidence=min(top_score, 1.0),
                target_types=[MemoryType.PROCEDURAL, MemoryType.SEMANTIC],
                target_subgraphs=["procedural"],
                type_weights={
                    MemoryType.PROCEDURAL: 1.6,
                    MemoryType.SEMANTIC: 1.1,
                    MemoryType.CLAIM: 1.0,
                    MemoryType.EPISODIC: 0.4,
                    MemoryType.CONVERSATION: 0.2,
                    MemoryType.PROFILE: 0.3,
                },
                routing_mode=mode,
            )

        if top_intent == QueryIntent.EPISODIC_CAUSAL:
            return IntentRoutingDecision(
                intent=QueryIntent.EPISODIC_CAUSAL,
                confidence=min(top_score, 1.0),
                target_types=[MemoryType.EPISODIC, MemoryType.CONVERSATION],
                target_subgraphs=["causal"],
                type_weights={
                    MemoryType.EPISODIC: 1.5,
                    MemoryType.CONVERSATION: 1.3,
                    MemoryType.CLAIM: 1.0,
                    MemoryType.SEMANTIC: 0.6,
                    MemoryType.PROCEDURAL: 0.4,
                    MemoryType.PROFILE: 0.5,
                },
                routing_mode=mode,
            )

        if top_intent == QueryIntent.USER_PROFILE:
            return IntentRoutingDecision(
                intent=QueryIntent.USER_PROFILE,
                confidence=min(top_score, 1.0),
                target_types=[MemoryType.PROFILE, MemoryType.SEMANTIC],
                target_subgraphs=["knowledge"],
                type_weights={
                    MemoryType.PROFILE: 1.6,
                    MemoryType.SEMANTIC: 0.9,
                    MemoryType.CLAIM: 0.8,
                    MemoryType.EPISODIC: 0.4,
                    MemoryType.CONVERSATION: 0.5,
                    MemoryType.PROCEDURAL: 0.5,
                },
                routing_mode=mode,
            )

        # QueryIntent.KNOWLEDGE_FACT
        return IntentRoutingDecision(
            intent=QueryIntent.KNOWLEDGE_FACT,
            confidence=min(top_score, 1.0),
            target_types=[MemoryType.SEMANTIC, MemoryType.CLAIM],
            target_subgraphs=["knowledge"],
            type_weights={
                MemoryType.SEMANTIC: 1.5,
                MemoryType.CLAIM: 1.4,
                MemoryType.PROCEDURAL: 0.8,
                MemoryType.EPISODIC: 0.5,
                MemoryType.CONVERSATION: 0.3,
                MemoryType.PROFILE: 0.3,
            },
            routing_mode=mode,
        )

    def _match_score(
        self,
        text: str,
        patterns: list[re.Pattern[str]],
        *,
        specificity_boost: float = 0.0,
    ) -> float:
        """Calculate aggregate match score across patterns."""
        matches = 0
        for pattern in patterns:
            found = pattern.findall(text)
            if found:
                matches += len(found)
        if matches == 0:
            return 0.0
        # 1 match gives ~0.72 (moderate confidence -> adaptive weighting)
        # 2+ matches or specificity boost gives >=0.86 (high confidence -> safe physical pruning)
        return min(0.58 + (matches * 0.14) + specificity_boost, 0.99)

    def _build_general_decision(self, confidence: float) -> IntentRoutingDecision:
        """Build fallback decision when no specific intent dominates."""
        return IntentRoutingDecision(
            intent=QueryIntent.GENERAL,
            confidence=confidence,
            target_types=[
                MemoryType.PROFILE,
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            ],
            target_subgraphs=["procedural", "causal", "knowledge"],
            type_weights={
                MemoryType.PROFILE: 1.0,
                MemoryType.SEMANTIC: 1.0,
                MemoryType.EPISODIC: 0.8,
                MemoryType.CONVERSATION: 0.95,
                MemoryType.PROCEDURAL: 0.9,
                MemoryType.CLAIM: 1.05,
            },
            routing_mode="broadcast",
        )


class KeywordBasedRecognizer(DeterministicIntentRouter):
    """Backward-compatible class wrapper preserving the historical name."""

    def __init__(
        self,
        fact_keywords: list[str] | None = None,
        preference_keywords: list[str] | None = None,
    ) -> None:
        super().__init__()
        # Custom keyword hooks can be passed if needed
        self._custom_fact_keywords = fact_keywords
        self._custom_preference_keywords = preference_keywords
