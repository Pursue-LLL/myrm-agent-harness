# [INPUT] myrm_agent_harness.toolkits.memory.types::BaseMemory (POS: Memory type system foundation)
# [INPUT] myrm_agent_harness.toolkits.memory.types::SemanticMemory (POS: Core semantic memory schema)
# [INPUT] myrm_agent_harness.toolkits.memory.types::EvidenceReference (POS: Structured provenance evidence anchoring this fact)
# [OUTPUT] MergeState: Enumeration of deterministic merge decisions (CONFIRM, SUPPLEMENT, CONFLICT, USER_OVERRIDE_PROTECTED, NEW)
# [OUTPUT] ConflictItem: Structured DTO representing an unadjudicated memory contradiction
# [OUTPUT] MergeDecision: Typed outcome of candidate vs existing memory evaluation
# [OUTPUT] ConfidenceEvolutionEngine: Smooth confidence evolution and temporal half-life self-healing engine
# [OUTPUT] DeterministicThreeStateMerger: Zero-LLM deterministic three-state conflict merger
# [POS] Deterministic memory conflict resolution and confidence evolution strategy. Resolves contradictions without LLM calls.

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    EvidenceReference,
    SemanticMemory,
)


class MergeState(StrEnum):
    """Deterministic merge states for memory consolidation and deduplication."""

    CONFIRM = "confirm"
    SUPPLEMENT = "supplement"
    CONFLICT = "conflict"
    USER_OVERRIDE_PROTECTED = "user_override_protected"
    NEW = "new"


class ConflictItem(BaseModel):
    """Structured DTO representing an unadjudicated contradiction between memories."""

    conflict_id: str = Field(default_factory=lambda: str(uuid4()))
    existing_memory_id: str
    candidate_content: str
    existing_content: str
    facet: str | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: str = "pending"
    activation_count: int = 1
    resolved_at: datetime | None = None
    resolution_action: str | None = None


class MergeDecision(BaseModel):
    """Typed outcome of candidate vs existing memory evaluation."""

    state: MergeState
    merged_content: str | None = None
    updated_confidence: float | None = None
    candidate_confidence: float | None = None
    merged_evidence: list[EvidenceReference] = Field(default_factory=list)
    conflict_item: ConflictItem | None = None
    reason: str = ""


class ConfidenceEvolutionEngine:
    """Calculates smooth confidence score shifts and temporal half-life self-healing."""

    CONFIRM_INCREMENT: float = 0.05
    MAX_CONFIDENCE: float = 0.98
    MIN_CONFIDENCE: float = 0.10
    CONFLICT_DECAY: float = 0.35
    TEMPORAL_WINDOW_DAYS: int = 14
    TEMPORAL_AUTO_RECONCILE_THRESHOLD: int = 3

    @classmethod
    def evolve_on_confirm(cls, existing_confidence: float) -> float:
        """Increment confidence upon repeated corroboration, capped at MAX_CONFIDENCE."""
        return min(cls.MAX_CONFIDENCE, round(existing_confidence + cls.CONFIRM_INCREMENT, 2))

    @classmethod
    def evolve_on_conflict(cls) -> tuple[float, float]:
        """Lower both conflicting memories to prevent contradictory retrieval in LLM prompts."""
        return (cls.CONFLICT_DECAY, cls.CONFLICT_DECAY)

    @classmethod
    def check_temporal_reconciliation(
        cls,
        conflict: ConflictItem,
        current_time: datetime | None = None,
    ) -> bool:
        """Check if repeated confirmation of the candidate fact warrants automatic adoption."""
        now = current_time or datetime.now(UTC)
        elapsed = now - conflict.detected_at
        if elapsed <= timedelta(days=cls.TEMPORAL_WINDOW_DAYS):
            return conflict.activation_count >= cls.TEMPORAL_AUTO_RECONCILE_THRESHOLD
        return False


class DeterministicThreeStateMerger:
    """Zero-LLM deterministic three-state conflict merger and evolution evaluator."""

    _MUTUALLY_EXCLUSIVE_FACETS: dict[str, list[str]] = {
        "location": ["常住", "住在", "位于", "搬到", "生活在", "工作地在", "工作在"],
        "runtime": ["使用 bun", "使用 node", "使用 deno", "使用 python 3.12", "使用 python 3.13"],
        "package_manager": ["用 uv", "用 pip", "用 poetry", "用 pnpm", "用 npm", "用 yarn", "用 bun"],
        "operating_system": ["macOS", "Linux", "Windows", "Ubuntu", "Arch"],
        "editor_ide": ["使用 Cursor", "使用 VS Code", "使用 Neovim", "使用 Emacs"],
    }

    _NEGATION_MARKERS: set[str] = {
        "不", "禁止", "严禁", "切勿", "不要", "禁用", "放弃", "不再", "停止",
        "never", "no", "not", "disable", "prohibit", "stop", "avoid",
    }

    def __init__(self, confidence_engine: type[ConfidenceEvolutionEngine] | None = None) -> None:
        self._engine = confidence_engine or ConfidenceEvolutionEngine

    def evaluate(
        self,
        existing: BaseMemory,
        candidate_content: str,
        candidate_evidence: list[EvidenceReference] | None = None,
        similarity: float = 0.0,
    ) -> MergeDecision:
        """Evaluate candidate content against existing memory using deterministic rules."""
        candidate_clean = candidate_content.strip()
        existing_clean = existing.content.strip()
        evidence_list = candidate_evidence or []

        # 1. Hard check: Human manual override lock protects against automated overwrite
        if getattr(existing, "is_user_locked", False):
            return MergeDecision(
                state=MergeState.USER_OVERRIDE_PROTECTED,
                merged_content=existing_clean,
                updated_confidence=getattr(existing, "confidence", 1.0),
                reason="Existing memory is locked by explicit human override.",
            )

        # 2. Exact or normalized identity: Confirm
        if self._is_identical_normalized(existing_clean, candidate_clean):
            existing_conf = getattr(existing, "confidence", 0.85)
            new_conf = self._engine.evolve_on_confirm(existing_conf)
            merged_ev = self._merge_evidence(existing.evidence, evidence_list)
            return MergeDecision(
                state=MergeState.CONFIRM,
                merged_content=existing_clean,
                updated_confidence=new_conf,
                merged_evidence=merged_ev,
                reason="Candidate verbatim or structurally matches existing fact.",
            )

        # 3. Check for single-valued facet contradiction (Conflict)
        facet_conflict = self._detect_facet_conflict(existing_clean, candidate_clean)
        if facet_conflict:
            conf_exist, conf_cand = self._engine.evolve_on_conflict()
            conflict_item = ConflictItem(
                existing_memory_id=existing.id,
                candidate_content=candidate_clean,
                existing_content=existing_clean,
                facet=facet_conflict,
            )
            return MergeDecision(
                state=MergeState.CONFLICT,
                updated_confidence=conf_exist,
                candidate_confidence=conf_cand,
                conflict_item=conflict_item,
                reason=f"Mutually exclusive value detected for facet '{facet_conflict}'.",
            )

        # 4. Check for negation or semantic opposition (Conflict)
        if self._detect_negation_inversion(existing_clean, candidate_clean):
            conf_exist, conf_cand = self._engine.evolve_on_conflict()
            conflict_item = ConflictItem(
                existing_memory_id=existing.id,
                candidate_content=candidate_clean,
                existing_content=existing_clean,
                facet="polarity_inversion",
            )
            return MergeDecision(
                state=MergeState.CONFLICT,
                updated_confidence=conf_exist,
                candidate_confidence=conf_cand,
                conflict_item=conflict_item,
                reason="Detected polarity/negation inversion between candidate and existing fact.",
            )

        # 5. Check for incremental detail expansion (Supplement)
        if self._is_supplement(existing_clean, candidate_clean):
            merged_content = self._merge_supplement_content(existing_clean, candidate_clean)
            merged_ev = self._merge_evidence(existing.evidence, evidence_list)
            return MergeDecision(
                state=MergeState.SUPPLEMENT,
                merged_content=merged_content,
                updated_confidence=getattr(existing, "confidence", 0.85),
                merged_evidence=merged_ev,
                reason="Candidate adds clarifying details or superset scope to existing fact.",
            )

        # 6. Fallback based on vector similarity threshold
        if similarity >= 0.94:
            existing_conf = getattr(existing, "confidence", 0.85)
            new_conf = self._engine.evolve_on_confirm(existing_conf)
            merged_ev = self._merge_evidence(existing.evidence, evidence_list)
            return MergeDecision(
                state=MergeState.CONFIRM,
                merged_content=existing_clean,
                updated_confidence=new_conf,
                merged_evidence=merged_ev,
                reason="High cosine similarity (>0.94) indicates identical semantic intent.",
            )

        if similarity >= 0.72:
            # Semantic proximity with distinct phrasing and non-overlapping facets
            conf_exist, conf_cand = self._engine.evolve_on_conflict()
            conflict_item = ConflictItem(
                existing_memory_id=existing.id,
                candidate_content=candidate_clean,
                existing_content=existing_clean,
                facet="semantic_ambiguity",
            )
            return MergeDecision(
                state=MergeState.CONFLICT,
                updated_confidence=conf_exist,
                candidate_confidence=conf_cand,
                conflict_item=conflict_item,
                reason="Moderate cosine similarity (0.72-0.94) indicates potential divergence.",
            )

        return MergeDecision(
            state=MergeState.NEW,
            reason="Candidate fact is orthogonal to existing memory.",
        )

    def _is_identical_normalized(self, a: str, b: str) -> bool:
        """Check if two strings are identical after normalizing whitespace and punctuation."""
        norm_a = re.sub(r"[\s\W_]+", "", a.lower(), flags=re.UNICODE)
        norm_b = re.sub(r"[\s\W_]+", "", b.lower(), flags=re.UNICODE)
        return norm_a == norm_b

    def _detect_facet_conflict(self, a: str, b: str) -> str | None:
        """Detect if both texts reference mutually exclusive values in a known facet."""
        lower_a = a.lower()
        lower_b = b.lower()
        for facet, patterns in self._MUTUALLY_EXCLUSIVE_FACETS.items():
            matched_a = [p for p in patterns if p.lower() in lower_a]
            matched_b = [p for p in patterns if p.lower() in lower_b]
            if matched_a and matched_b:
                if set(matched_a) != set(matched_b):
                    return facet
        return None

    def _detect_negation_inversion(self, a: str, b: str) -> bool:
        """Detect if one text has explicit negation while the other affirms the same concept."""
        tokens_a = set(re.findall(r"\w+", a.lower()))
        tokens_b = set(re.findall(r"\w+", b.lower()))
        has_neg_a = bool(tokens_a & self._NEGATION_MARKERS)
        has_neg_b = bool(tokens_b & self._NEGATION_MARKERS)

        if has_neg_a != has_neg_b:
            pos_tokens_a = tokens_a - self._NEGATION_MARKERS
            pos_tokens_b = tokens_b - self._NEGATION_MARKERS
            overlap = pos_tokens_a & pos_tokens_b
            if len(overlap) >= 2:
                return True
        return False

    def _is_supplement(self, existing: str, candidate: str) -> bool:
        """Check if candidate adds incremental details to existing without contradiction."""
        if existing in candidate and len(candidate) > len(existing):
            return True
        tokens_exist = set(re.findall(r"\w+", existing.lower()))
        tokens_cand = set(re.findall(r"\w+", candidate.lower()))
        if tokens_exist and tokens_exist.issubset(tokens_cand) and len(tokens_cand) > len(tokens_exist):
            return True
        return False

    def _merge_supplement_content(self, existing: str, candidate: str) -> str:
        """Merge incremental candidate content into existing fact."""
        if existing in candidate:
            return candidate
        return f"{existing}；补充：{candidate}"

    def _merge_evidence(
        self,
        existing_ev: list[EvidenceReference],
        candidate_ev: list[EvidenceReference],
    ) -> list[EvidenceReference]:
        """Union and deduplicate structured evidence anchors by message_id or quote."""
        seen_keys: set[str] = set()
        merged: list[EvidenceReference] = []

        for ev in list(existing_ev) + list(candidate_ev):
            key = f"{ev.source_type}:{ev.message_id or ''}:{ev.quote_snippet or ''}"
            if key not in seen_keys:
                seen_keys.add(key)
                merged.append(ev)
        return merged
