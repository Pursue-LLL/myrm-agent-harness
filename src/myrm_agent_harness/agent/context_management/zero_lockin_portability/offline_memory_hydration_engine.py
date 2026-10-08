# [INPUT] ArchivedSessionTree, ArchivedSessionNode, HydratedUserProfile, ExtractedEntityFact from .portability_types
# [OUTPUT] OfflineMemoryProfileHydrationEngine
# [POS] Offline heuristic and entity extraction engine generating long-term memory facts and profiles from historical transcripts

"""Offline memory and profile hydration engine for zero-lockin context portability."""

from __future__ import annotations

from collections import Counter
import re
import time
import uuid

from .portability_types import (
    ArchivedSessionTree,
    ExtractedEntityFact,
    HydratedUserProfile,
    MemoryFactCategory,
)

COMMON_TECH_STACK_KEYWORDS: set[str] = {
    "python",
    "typescript",
    "javascript",
    "rust",
    "golang",
    "react",
    "vue",
    "svelte",
    "fastapi",
    "django",
    "flask",
    "next.js",
    "docker",
    "kubernetes",
    "postgres",
    "postgresql",
    "sqlite",
    "redis",
    "qdrant",
    "tailwind",
    "pytorch",
    "tensorflow",
    "langchain",
    "langgraph",
}

PREFERENCE_PATTERNS: list[tuple[re.Pattern[str], MemoryFactCategory, str, float]] = [
    (
        re.compile(r"(?:i prefer|prefer to use|always use|please use)\s+([^.,;\n]+)", re.IGNORECASE),
        "preference",
        "prefers",
        0.85,
    ),
    (
        re.compile(r"(?:never use|don't use|do not use|avoid)\s+([^.,;\n]+)", re.IGNORECASE),
        "constraint",
        "avoids",
        0.90,
    ),
    (
        re.compile(r"(?:our project is|project name is|building a|working on)\s+([^.,;\n]+)", re.IGNORECASE),
        "project_context",
        "works_on",
        0.80,
    ),
    (
        re.compile(r"(?:my role is|i am a|i work as)\s+([^.,;\n]+)", re.IGNORECASE),
        "preference",
        "role_is",
        0.95,
    ),
    (
        re.compile(r"(?:coding style|code style|follow)\s+([^.,;\n]+)", re.IGNORECASE),
        "coding_style",
        "follows_style",
        0.85,
    ),
]


class OfflineMemoryProfileHydrationEngine:
    """Extracts facts, habits, and user profiles offline from imported conversational trees."""

    @classmethod
    def hydrate_profile(
        cls,
        sessions: list[ArchivedSessionTree],
        user_id: str = "sovereign_user",
        min_confidence: float = 0.60,
    ) -> HydratedUserProfile:
        """Run offline rule-based and frequency extraction over user messages to synthesize profile."""
        facts: list[ExtractedEntityFact] = []
        tech_counter: Counter[str] = Counter()
        topic_counter: Counter[str] = Counter()
        coding_rules: list[str] = []
        preferred_languages: set[str] = set()

        for tree in sessions:
            for node_id, node in tree.nodes.items():
                if node.role != "user" or not node.content:
                    continue

                content = node.content.strip()
                content_lower = content.lower()

                # 1. Tech stack keyword detection
                for tech in COMMON_TECH_STACK_KEYWORDS:
                    # Match exact word boundaries
                    pattern = rf"\b{re.escape(tech)}\b"
                    if re.search(pattern, content_lower):
                        tech_counter[tech] += 1
                        if tech in ("python", "typescript", "javascript", "rust", "golang"):
                            preferred_languages.add(tech)

                # 2. Extract heuristic facts via regex patterns
                for regex, category, predicate, base_conf in PREFERENCE_PATTERNS:
                    matches = regex.findall(content)
                    for match_text in matches:
                        clean_val = match_text.strip()
                        if len(clean_val) < 3 or len(clean_val) > 80:
                            continue

                        fact_id = f"fact_{uuid.uuid4().hex[:12]}"
                        fact = ExtractedEntityFact(
                            fact_id=fact_id,
                            category=category,
                            subject=user_id,
                            predicate=predicate,
                            object_value=clean_val,
                            confidence=base_conf,
                            source_session_id=tree.session_id,
                            context_snippet=content[:120],
                        )
                        if fact.confidence >= min_confidence:
                            facts.append(fact)
                            if category == "coding_style":
                                coding_rules.append(clean_val)

                # 3. Topic keywords from session title & content
                words = re.findall(r"\b[A-Za-z]{4,}\b", content)
                for w in words:
                    w_low = w.lower()
                    if w_low not in COMMON_TECH_STACK_KEYWORDS and w_low not in ("with", "that", "this", "have", "from", "what", "make", "when"):
                        topic_counter[w_low] += 1

        # Aggregate top tech tags (mentioned at least once)
        top_tech_tags = [tech for tech, _ in tech_counter.most_common(12)]
        top_topics = [topic for topic, count in topic_counter.most_common(10) if count >= 2]

        # Dedup coding rules
        dedup_coding_rules = list(dict.fromkeys(coding_rules))

        return HydratedUserProfile(
            user_id=user_id,
            preferred_languages=sorted(list(preferred_languages)),
            tech_stack_tags=top_tech_tags,
            coding_style_rules=dedup_coding_rules,
            high_frequency_topics=top_topics,
            facts=facts,
            hydration_timestamp=time.time(),
        )

    @classmethod
    def filter_high_confidence_facts(
        cls, profile: HydratedUserProfile, threshold: float = 0.80
    ) -> list[ExtractedEntityFact]:
        """Filter and return only facts meeting the strict confidence barrier."""
        return [f for f in profile.facts if f.confidence >= threshold]
