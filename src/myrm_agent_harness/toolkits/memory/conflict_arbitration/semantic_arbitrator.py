# [POS] src/myrm_agent_harness/toolkits/memory/conflict_arbitration/semantic_arbitrator.py
# [INPUT] .types (ArbitrationAssessment, ConflictResolutionKind, ConflictSeverity, SemanticConflictRecord)
# [OUTPUT] MemorySemanticArbitrator

import logging
import re

from .types import (
    ArbitrationAssessment,
    ConflictResolutionKind,
    ConflictSeverity,
    SemanticConflictRecord,
)

logger = logging.getLogger(__name__)

# Heuristic patterns for explicit supersede / replacement intent
_OVERRIDE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(更正为|调整为|取代|废止|废除|变更成|修改为)", re.IGNORECASE),
    re.compile(r"\b(supersede[ds]?|replace[ds]?|updated to|changed to|canceled)\b", re.IGNORECASE),
    re.compile(r"(不再使用|已弃用|废除原方案|推翻原结论)", re.IGNORECASE),
]

# Heuristic patterns for complementary / merge intent
_MERGE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(同时|补充|另外|此外|兼顾|并存|附带)", re.IGNORECASE),
    re.compile(r"\b(also|additionally|in addition|along with|both|supplement)\b", re.IGNORECASE),
]


class MemorySemanticArbitrator:
    """Semantic arbitrator for memory conflicts and divergence analysis.

    Analyzes conflicting facts to determine whether they can be merged, overridden,
    or must be suspended for human arbitration card review.
    """

    def __init__(self, confidence_threshold: float = 0.85) -> None:
        self.confidence_threshold: float = confidence_threshold

    def evaluate_conflict(self, record: SemanticConflictRecord) -> ArbitrationAssessment:
        """Evaluate a semantic conflict record and produce an assessment."""
        # 1. If existing memory is protected by a user-confirmed freeze lock
        if record.is_existing_frozen:
            return ArbitrationAssessment(
                conflict_id=record.conflict_id,
                resolution_kind=ConflictResolutionKind.FREEZE_BLOCKED,
                confidence=1.0,
                reasoning=(
                    f"Existing memory '{record.existing_memory_id}' is protected by an active "
                    "UserConfirmedFreezeLock. Automated mutation is prohibited."
                ),
                suggested_text=record.existing_fact_text,
                requires_human_confirmation=True,
            )

        existing_clean = record.existing_fact_text.strip()
        candidate_clean = record.candidate_fact_text.strip()

        # 2. Identical content -> trivially merge / no-op
        if existing_clean.lower() == candidate_clean.lower():
            return ArbitrationAssessment(
                conflict_id=record.conflict_id,
                resolution_kind=ConflictResolutionKind.MERGE,
                confidence=1.0,
                reasoning="Candidate content is identical to existing fact.",
                suggested_text=existing_clean,
                requires_human_confirmation=False,
            )

        # 3. Check for explicit override intent
        is_explicit_override, override_reason = self._detect_override_intent(candidate_clean)
        if is_explicit_override:
            return ArbitrationAssessment(
                conflict_id=record.conflict_id,
                resolution_kind=ConflictResolutionKind.OVERRIDE,
                confidence=0.92,
                reasoning=f"Detected explicit override indicators: {override_reason}",
                suggested_text=candidate_clean,
                requires_human_confirmation=False,
            )

        # 4. Check for complementary merge intent
        is_merge_candidate, merge_reason = self._detect_merge_intent(
            existing_clean, candidate_clean
        )
        if is_merge_candidate:
            merged_content = self._synthesize_merged_fact(
                record.entity_key,
                record.attribute_name,
                existing_clean,
                candidate_clean,
            )
            return ArbitrationAssessment(
                conflict_id=record.conflict_id,
                resolution_kind=ConflictResolutionKind.MERGE,
                confidence=0.88,
                reasoning=f"Detected complementary information: {merge_reason}",
                suggested_text=merged_content,
                requires_human_confirmation=False,
            )

        # 5. Direct contradiction or ambiguous conflict -> Require human arbitration
        severity_reason = (
            f"Contradictory values detected for attribute '{record.attribute_name}' of "
            f"entity '{record.entity_key}' without explicit supersede or merge syntax."
        )
        return ArbitrationAssessment(
            conflict_id=record.conflict_id,
            resolution_kind=ConflictResolutionKind.CONTRADICTION,
            confidence=0.60,
            reasoning=severity_reason,
            suggested_text=existing_clean,
            requires_human_confirmation=True,
        )

    def detect_conflict_between_facts(
        self,
        conflict_id: str,
        entity_key: str,
        attribute_name: str,
        existing_memory_id: str,
        existing_fact_text: str,
        candidate_fact_text: str,
        is_existing_frozen: bool = False,
        source_context: str = "",
    ) -> SemanticConflictRecord:
        """Create a SemanticConflictRecord after comparing two facts on the same entity attribute."""
        severity = ConflictSeverity.MEDIUM
        if is_existing_frozen:
            severity = ConflictSeverity.CRITICAL

        return SemanticConflictRecord(
            conflict_id=conflict_id,
            entity_key=entity_key,
            attribute_name=attribute_name,
            existing_memory_id=existing_memory_id,
            existing_fact_text=existing_fact_text,
            candidate_fact_text=candidate_fact_text,
            severity=severity,
            source_context=source_context,
            is_existing_frozen=is_existing_frozen,
        )

    def _detect_override_intent(self, text: str) -> tuple[bool, str]:
        for pattern in _OVERRIDE_PATTERNS:
            match = pattern.search(text)
            if match:
                return True, f"matched pattern '{match.group(0)}'"
        return False, ""

    def _detect_merge_intent(self, existing: str, candidate: str) -> tuple[bool, str]:
        for pattern in _MERGE_PATTERNS:
            match = pattern.search(candidate)
            if match:
                return True, f"matched merge keyword '{match.group(0)}'"

        # If length and vocabulary differ substantially without negative polarity, treat as additive
        return False, ""

    def _synthesize_merged_fact(
        self,
        entity_key: str,
        attribute_name: str,
        existing_text: str,
        candidate_text: str,
    ) -> str:
        """Deterministically combine complementary facts."""
        return f"{existing_text}; 补充: {candidate_text}"
