"""Grounded Dreaming Engine.

Performs idle-time cross-session memory consolidation, clustering fragmented
facts from multiple conversational sessions, resolving cross-session conflicts,
and distilling human-readable cognitive insights into the Dream Diary.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamDiaryEntry,
    DreamSessionFragment,
)

_TOKEN_REGEX = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


class GroundedDreamingEngine:
    """Consolidates cross-session conversational memory fragments during idle cycles."""

    def __init__(self, similarity_threshold: float = 0.35) -> None:
        self._similarity_threshold = similarity_threshold

    @classmethod
    def _tokenize(cls, text: str) -> set[str]:
        """Extract alphanumeric and CJK word tokens."""
        return {tok.lower() for tok in _TOKEN_REGEX.findall(text) if len(tok) > 1}

    @classmethod
    def _jaccard_similarity(cls, tokens_a: set[str], tokens_b: set[str]) -> float:
        """Calculate Jaccard index between two token sets."""
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        return float(intersection / union) if union > 0 else 0.0

    def process_fragments(
        self,
        fragments: Sequence[DreamSessionFragment],
    ) -> list[DreamDiaryEntry]:
        """Process multiple session fragments into consolidated dream diary entries."""
        if not fragments:
            return []

        # 1. Flatten memory facts into unified candidates with origin tracking
        candidates: list[dict[str, object]] = []
        for frag in fragments:
            for mem in frag.memories:
                content = str(mem.get("content", "")).strip()
                if not content:
                    continue
                evidences = mem.get("evidence")
                evidence_snippets: list[str] = []
                if isinstance(evidences, list):
                    for ev in evidences:
                        if isinstance(ev, dict) and ev.get("quote_snippet"):
                            evidence_snippets.append(str(ev["quote_snippet"]))
                        elif isinstance(ev, str):
                            evidence_snippets.append(ev)

                candidates.append(
                    {
                        "session_id": frag.session_id,
                        "content": content,
                        "tokens": self._tokenize(content),
                        "evidence_snippets": evidence_snippets,
                        "confidence": float(mem.get("confidence", 0.5)),  # type: ignore[arg-type]
                    }
                )

        if not candidates:
            return []

        # 2. Cluster candidate facts across sessions
        clusters: list[list[dict[str, object]]] = []
        for cand in candidates:
            cand_tokens = cand["tokens"]
            assert isinstance(cand_tokens, set)
            matched_cluster: list[dict[str, object]] | None = None
            for cluster in clusters:
                # Compare candidate against cluster centroid / members
                for member in cluster:
                    member_tokens = member["tokens"]
                    assert isinstance(member_tokens, set)
                    sim = self._jaccard_similarity(cand_tokens, member_tokens)
                    if sim >= self._similarity_threshold:
                        matched_cluster = cluster
                        break
                if matched_cluster is not None:
                    break

            if matched_cluster is not None:
                matched_cluster.append(cand)
            else:
                clusters.append([cand])

        # 3. Distill clusters into DreamDiaryEntries
        entries: list[DreamDiaryEntry] = []
        for cluster in clusters:
            session_ids = sorted({str(m["session_id"]) for m in cluster})
            all_snippets: list[str] = []
            for m in cluster:
                snippets = m.get("evidence_snippets")
                if isinstance(snippets, list):
                    for s in snippets:
                        if isinstance(s, str) and s and s not in all_snippets:
                            all_snippets.append(s)

            # Synthesize representative statement
            # Pick the longest or highest-confidence item as base
            best_cand = max(
                cluster,
                key=lambda x: (
                    float(x.get("confidence", 0.5)),  # type: ignore[arg-type]
                    len(str(x.get("content", ""))),
                ),
            )
            base_statement = str(best_cand["content"])

            # Cross-session reinforcement bonus
            session_count = len(session_ids)
            if session_count >= 2:
                statement = f"[Cross-Session Validated] {base_statement}"
                conf_delta = min(0.35, 0.1 * session_count)
            else:
                statement = base_statement
                conf_delta = 0.1

            entries.append(
                DreamDiaryEntry.create(
                    cognitive_statement=statement,
                    source_session_ids=session_ids,
                    evidence_snippets=all_snippets[:5],
                    confidence_delta=round(conf_delta, 2),
                )
            )

        # Sort entries: cross-session reinforced insights first
        entries.sort(
            key=lambda e: (len(e.source_session_ids), e.confidence_delta),
            reverse=True,
        )
        return entries
