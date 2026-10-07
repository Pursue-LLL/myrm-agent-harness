"""Dual-Track Decision Tracer engine decoupling high-privilege state facts and verbatim evidence.

[INPUT]
- toolkits.memory.dual_track.models::DualTrackAssembly, EvidenceExpansionReport, FactDecisionEntry,
  VerbatimEvidenceSlice (POS: Data models for Dual-Track Fact Decision and Verbatim Evidence Tracer Engine.)

[OUTPUT]
- DualTrackDecisionTracer: Manages high-privilege state facts for instant decisions while retaining lazy
  verbatim evidence handles.

[POS]
Dual-Track Decision Tracer engine decoupling high-privilege state facts and verbatim evidence.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    DualTrackAssembly,
    EvidenceExpansionReport,
    FactDecisionEntry,
    VerbatimEvidenceSlice,
)


class DualTrackDecisionTracer:
    """Manages high-privilege state facts for instant decisions while retaining lazy verbatim evidence handles."""

    def __init__(self) -> None:
        """Initialize dual-track registries for facts and evidence slices."""
        self._facts_by_key: dict[str, FactDecisionEntry] = {}
        self._key_by_fact_id: dict[str, str] = {}
        self._evidence_store: dict[str, VerbatimEvidenceSlice] = {}

    @property
    def total_facts(self) -> int:
        """Return total count of stored structured facts."""
        return len(self._facts_by_key)

    @property
    def total_evidence_slices(self) -> int:
        """Return total count of stored verbatim evidence slices."""
        return len(self._evidence_store)

    def register_evidence(self, evidence: VerbatimEvidenceSlice) -> str:
        """Store an immutable verbatim conversational evidence slice.

        Args:
            evidence: The verbatim conversational snippet and source metadata.

        Returns:
            The evidence identifier string.
        """
        self._evidence_store[evidence.evidence_id] = evidence
        return evidence.evidence_id

    def set_fact(
        self,
        key: str,
        value: str,
        evidence_ids: Sequence[str] | None = None,
        confidence: float = 1.0,
        scope: str = "workspace",
        custom_now: datetime | None = None,
    ) -> FactDecisionEntry:
        """Record or update an authoritative state fact with bidirectional evidence pointers.

        Args:
            key: Canonical state key.
            value: Current state value.
            evidence_ids: Pointers to supporting verbatim evidence records.
            confidence: Certainty score (0.0 to 1.0).
            scope: Operational scope name.
            custom_now: Optional deterministic timestamp.

        Returns:
            The updated FactDecisionEntry.
        """
        now = custom_now or datetime.now(UTC)
        norm_key = key.strip()

        # Validate that referenced evidence IDs exist or preserve pointers
        valid_ev_ids: list[str] = list(evidence_ids) if evidence_ids else []

        if norm_key in self._facts_by_key:
            entry = self._facts_by_key[norm_key]
            entry.value = value.strip()
            entry.confidence = confidence
            entry.scope = scope
            entry.updated_at = now
            # Append any newly supplied evidence pointers without duplicates
            for eid in valid_ev_ids:
                if eid not in entry.evidence_ref_ids:
                    entry.evidence_ref_ids.append(eid)
            return entry

        fact_id = f"fact-{uuid.uuid4().hex[:12]}"
        entry = FactDecisionEntry(
            fact_id=fact_id,
            key=norm_key,
            value=value.strip(),
            confidence=confidence,
            scope=scope,
            evidence_ref_ids=valid_ev_ids,
            created_at=now,
            updated_at=now,
        )

        self._facts_by_key[norm_key] = entry
        self._key_by_fact_id[fact_id] = norm_key
        return entry

    def get_fact(self, key_or_id: str) -> FactDecisionEntry | None:
        """Retrieve a fact by canonical key or by fact_id."""
        if key_or_id in self._facts_by_key:
            return self._facts_by_key[key_or_id]
        if key_or_id in self._key_by_fact_id:
            return self._facts_by_key.get(self._key_by_fact_id[key_or_id])
        return None

    def list_facts(self, scope: str | None = None) -> list[FactDecisionEntry]:
        """List all facts, optionally filtered by scope."""
        if scope is None:
            return list(self._facts_by_key.values())
        return [f for f in self._facts_by_key.values() if f.scope == scope]

    def assemble_state_for_prompt(self, scope: str | None = None) -> DualTrackAssembly:
        """Synthesize ultra-compact KV state block for top-level prompt injection (Track 1).

        Zero conversational verbatim clutter; provides pure deterministic truth at minimal tokens.
        """
        facts = self.list_facts(scope)
        if not facts:
            return DualTrackAssembly(
                state_prompt_segment="",
                active_fact_count=0,
                lazy_evidence_handles=[],
                estimated_tokens=0,
            )

        lines: list[str] = [
            "[SYSTEM DETERMINISTIC STATE - CANONICAL TRUTH]",
            "The following verified state facts are authoritative and non-negotiable:",
        ]

        all_handles: list[str] = []

        for f in sorted(facts, key=lambda x: x.key):
            ref_str = f" [evidence: {', '.join(f.evidence_ref_ids)}]" if f.evidence_ref_ids else ""
            lines.append(f"  - {f.key} = {f.value} (conf: {f.confidence:.2f}){ref_str}")
            all_handles.extend(f.evidence_ref_ids)

        lines.append("[END DETERMINISTIC STATE]")
        segment = "\n".join(lines)

        # Approximate token count (roughly 4 characters per token)
        est_tokens = max(1, len(segment) // 4)

        return DualTrackAssembly(
            state_prompt_segment=segment,
            active_fact_count=len(facts),
            lazy_evidence_handles=sorted(set(all_handles)),
            estimated_tokens=est_tokens,
        )

    def expand_evidence_for_fact(self, fact_key_or_id: str) -> EvidenceExpansionReport:
        """Lazy-unroll full verbatim conversational evidence for a fact upon audit/drill-down (Track 2).

        Args:
            fact_key_or_id: Fact key or unique fact_id.

        Returns:
            EvidenceExpansionReport with unrolled slices and provenance commentary.

        Raises:
            KeyError: If fact cannot be found.
        """
        fact = self.get_fact(fact_key_or_id)
        if fact is None:
            raise KeyError(f"Fact '{fact_key_or_id}' does not exist in registry.")

        matched_slices: list[VerbatimEvidenceSlice] = []
        for eid in fact.evidence_ref_ids:
            if eid in self._evidence_store:
                matched_slices.append(self._evidence_store[eid])

        # Sort evidence chronologically
        matched_slices.sort(key=lambda s: s.timestamp)

        total_chars = sum(len(s.snippet) for s in matched_slices)
        rationale = (
            f"Fact '{fact.key}' is corroborated by {len(matched_slices)} verbatim "
            f"conversational slice(s) spanning {total_chars} characters."
        )

        return EvidenceExpansionReport(
            fact_id=fact.fact_id,
            fact_key=fact.key,
            fact_value=fact.value,
            matched_evidence_slices=matched_slices,
            synthesis_rationale=rationale,
            total_evidence_characters=total_chars,
        )
