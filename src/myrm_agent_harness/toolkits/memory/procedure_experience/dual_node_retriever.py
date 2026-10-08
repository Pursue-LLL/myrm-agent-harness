"""Fixed-count dual-node retriever for procedure-shaped experience memories.

[INPUT]
- toolkits.memory.procedure_experience.models::DualNodeRetrievalQuery, DualNodeRetrievalResult,
  ProcedureMemoryEntry, RetrievalNodeKind (POS: Types and models for procedure experience.)
- toolkits.memory.procedure_experience.procedure_protocol::ProcedureProtocolEngine (POS: Protocol validation,
  compact anchor synthesis, and multi-intent decomposition engine.)

[OUTPUT]
- DualNodeFixedCountRetriever: Fixed-count dual-node retriever for procedure-shaped experience memories.

[POS]
Fixed-count dual-node retriever for procedure-shaped experience memories.
"""

# [POS]: src/myrm_agent_harness/toolkits/memory/procedure_experience/dual_node_retriever.py
# [INPUT]: src.myrm_agent_harness.toolkits.memory.procedure_experience (models, procedure_protocol)
# [OUTPUT]: DualNodeFixedCountRetriever

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.memory.procedure_experience.models import (
    DualNodeRetrievalQuery,
    DualNodeRetrievalResult,
    ProcedureMemoryEntry,
    RetrievalNodeKind,
)
from myrm_agent_harness.toolkits.memory.procedure_experience.procedure_protocol import (
    ProcedureProtocolEngine,
)


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lower-case words and CJK n-grams for zero-dependency multilingual matching."""
    words = re.findall(r"\w+", text.lower())
    tokens = set(words)
    for w in words:
        cjk_chars = [c for c in w if "\u4e00" <= c <= "\u9fff"]
        if cjk_chars:
            tokens.update(cjk_chars)
            for i in range(len(cjk_chars) - 1):
                tokens.add("".join(cjk_chars[i : i + 2]))
    return tokens


class DualNodeFixedCountRetriever:
    """Fixed-count dual-node retriever for procedure-shaped experience memories."""

    def __init__(self, protocol_engine: ProcedureProtocolEngine | None = None) -> None:
        self._protocol_engine = protocol_engine or ProcedureProtocolEngine()
        self._entries: dict[str, ProcedureMemoryEntry] = {}

    def register(self, entry: ProcedureMemoryEntry) -> ProcedureMemoryEntry:
        """Register and index an 8-field procedure memory entry with automatic anchor generation."""
        violations = self._protocol_engine.validate_protocol(entry)
        if violations:
            raise ValueError(f"ProcedureMemoryEntry protocol violation: {'; '.join(violations)}")

        if not entry.retrieval_anchor:
            entry.retrieval_anchor = self._protocol_engine.generate_retrieval_anchor(
                operation_intent=entry.operation_intent,
                preconditions=entry.preconditions,
                applicability=entry.applicability,
            )

        self._entries[entry.entry_id] = entry
        return entry

    def get_entry(self, entry_id: str) -> ProcedureMemoryEntry | None:
        """Retrieve entry by unique identifier."""
        return self._entries.get(entry_id)

    def retrieve(self, query: DualNodeRetrievalQuery) -> DualNodeRetrievalResult:
        """Execute fixed-count dual-node retrieval targeting first-user or pre-write intercept sites."""
        q_tokens = _tokenize(query.query_text)
        scored_candidates: list[tuple[float, ProcedureMemoryEntry]] = []

        for entry in self._entries.values():
            score = 0.0

            # Match against compact anchor
            anchor_tokens = _tokenize(entry.retrieval_anchor)
            common_anchor = q_tokens.intersection(anchor_tokens)
            score += len(common_anchor) * 3.0

            # Match against name
            name_tokens = _tokenize(entry.name)
            score += len(q_tokens.intersection(name_tokens)) * 2.0

            # Dual-node bias weighting
            if query.node_kind == RetrievalNodeKind.FIRST_USER:
                # Prioritize macro operation intent and applicability
                intent_tokens = set(re.findall(r"\w+", entry.operation_intent.lower()))
                app_tokens = set(re.findall(r"\w+", " ".join(entry.applicability).lower()))
                score += len(q_tokens.intersection(intent_tokens)) * 2.5
                score += len(q_tokens.intersection(app_tokens)) * 1.5
            elif query.node_kind == RetrievalNodeKind.PRE_WRITE:
                # Prioritize immutable boundaries, anti-patterns, and write field provenance
                bound_tokens = set(re.findall(r"\w+", " ".join(entry.immutable_boundary).lower()))
                anti_tokens = set(re.findall(r"\w+", " ".join(entry.anti_patterns).lower()))
                write_tokens = set(re.findall(r"\w+", " ".join(entry.write_field_provenance.keys()).lower()))
                score += len(q_tokens.intersection(bound_tokens)) * 2.5
                score += len(q_tokens.intersection(anti_tokens)) * 2.0
                score += len(q_tokens.intersection(write_tokens)) * 2.0

            # Factor in entry confidence
            score *= entry.confidence

            if score > 0.0:
                scored_candidates.append((score, entry))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        # Fixed-count slice: take top_n items
        top_entries = [entry for _, entry in scored_candidates[: query.top_n]]

        return DualNodeRetrievalResult(
            node_kind=query.node_kind,
            matched_entries=top_entries,
            total_matched=len(top_entries),
        )

    def list_all(self) -> list[ProcedureMemoryEntry]:
        """List all registered procedure memory entries."""
        return list(self._entries.values())
