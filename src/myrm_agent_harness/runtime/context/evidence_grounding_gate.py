"""Evidence-based locator grounding protocol and anti-hallucination gate.

Implements MFS Search->Locate->Browse paradigm: search returns candidate hits with
structured locators, mandatory evidence re-reading verifies ground truth, and the
grounding gate validates that generated answers are strictly anchored in authentic evidence.

[INPUT]
- runtime.context.evidence_grounding_types::GroundingAuditResult, SearchCandidateHit, StructuredLocator,
  VerifiedEvidence (POS: Type definitions for evidence-based locator grounding protocol and
  anti-hallucination gate.)

[OUTPUT]
- EvidenceGroundingProtocolHub: Orchestrates candidate registration, mandatory evidence re-reading, and
  anti-hallucination grounding audits.

[POS]
Evidence-based locator grounding protocol and anti-hallucination gate.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import uuid
from collections.abc import Callable, Sequence

from myrm_agent_harness.runtime.context.evidence_grounding_types import (
    GroundingAuditResult,
    SearchCandidateHit,
    StructuredLocator,
    VerifiedEvidence,
)

logger = logging.getLogger(__name__)

EvidenceFetcherCallable = Callable[[str, StructuredLocator], str]


class EvidenceGroundingProtocolHub:
    """Orchestrates candidate registration, mandatory evidence re-reading, and anti-hallucination grounding audits."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._candidates: dict[str, SearchCandidateHit] = {}
        self._verified_evidence: dict[str, VerifiedEvidence] = {}

    def register_search_candidate(
        self,
        source_uri: str,
        locator: StructuredLocator,
        snippet_preview: str,
        score: float = 1.0,
    ) -> SearchCandidateHit:
        """Register a search candidate hit carrying structured locator coordinates."""
        hit_id = f"hit_{uuid.uuid4().hex[:10]}"
        candidate = SearchCandidateHit(
            hit_id=hit_id,
            source_uri=source_uri,
            locator=locator,
            score=score,
            snippet_preview=snippet_preview,
            is_verified=False,
        )
        with self._lock:
            self._candidates[hit_id] = candidate
        logger.debug("Registered search candidate: %s (%s)", hit_id, locator.to_display_string())
        return candidate

    def browse_evidence(
        self,
        hit_id: str,
        fetcher_callable: EvidenceFetcherCallable,
    ) -> VerifiedEvidence:
        """Mandatory evidence re-reading: open authentic canonical object at locator coordinates."""
        with self._lock:
            candidate = self._candidates.get(hit_id)
            if candidate is None:
                raise KeyError(f"Candidate hit not found: {hit_id}")

        # Execute canonical fetch through provided callback
        raw_content = fetcher_callable(candidate.source_uri, candidate.locator)
        content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()[:16]

        evidence_id = f"ev_{uuid.uuid4().hex[:10]}"
        verified = VerifiedEvidence(
            evidence_id=evidence_id,
            hit_id=hit_id,
            source_uri=candidate.source_uri,
            locator=candidate.locator,
            raw_content=raw_content,
            content_hash=content_hash,
        )

        with self._lock:
            self._verified_evidence[evidence_id] = verified
            # Mark provisional hit as verified
            self._candidates[hit_id] = SearchCandidateHit(
                hit_id=candidate.hit_id,
                source_uri=candidate.source_uri,
                locator=candidate.locator,
                score=candidate.score,
                snippet_preview=candidate.snippet_preview,
                is_verified=True,
            )

        logger.debug("Verified authentic evidence: %s from %s", evidence_id, candidate.source_uri)
        return verified

    def audit_grounding(
        self,
        claimed_evidence_ids: Sequence[str],
        answer_content: str,
        min_overlap_tokens: int = 1,
    ) -> GroundingAuditResult:
        """Anti-hallucination gate: audit whether claims cite registered, verified evidence with real content anchoring."""
        total_claims = len(claimed_evidence_ids)
        if total_claims == 0:
            # If answer is significant and claims zero evidence
            is_substantial = len(answer_content.strip()) > 50
            return GroundingAuditResult(
                is_grounded=not is_substantial,
                total_claims_count=0,
                grounded_claims_count=0,
                missing_evidence_reasons=(
                    ["Substantial assertion generated without citing any verified evidence"]
                    if is_substantial
                    else []
                ),
                confidence_score=1.0 if not is_substantial else 0.0,
            )

        grounded_count = 0
        reasons: list[str] = []

        with self._lock:
            verified_map = dict(self._verified_evidence)

        # Normalize words in answer
        answer_words = set(re.findall(r"\b\w{3,}\b", answer_content.lower()))

        for ev_id in claimed_evidence_ids:
            ev = verified_map.get(ev_id)
            if ev is None:
                reasons.append(f"Cited unverified or non-existent evidence id: {ev_id}")
                continue

            # Check lexical anchoring between answer and authentic evidence
            evidence_words = set(re.findall(r"\b\w{3,}\b", ev.raw_content.lower()))
            overlap = answer_words.intersection(evidence_words)

            if len(overlap) < min_overlap_tokens:
                reasons.append(
                    f"Evidence {ev_id} ({ev.source_uri}) has insufficient lexical overlap with answer"
                )
                continue

            grounded_count += 1

        confidence = grounded_count / total_claims if total_claims > 0 else 0.0
        is_grounded = grounded_count == total_claims

        return GroundingAuditResult(
            is_grounded=is_grounded,
            total_claims_count=total_claims,
            grounded_claims_count=grounded_count,
            missing_evidence_reasons=reasons,
            confidence_score=round(confidence, 3),
        )

    def format_grounded_citation(self, evidence_id: str) -> str:
        """Render standardized markdown citation token with authentic locator."""
        with self._lock:
            ev = self._verified_evidence.get(evidence_id)
        if ev is None:
            return f"[Evidence #{evidence_id}](unverified)"

        coord_str = ev.locator.to_display_string()
        return f"[Evidence #{evidence_id}]({ev.source_uri}#{coord_str})"

    def get_verified_evidence(self, evidence_id: str) -> VerifiedEvidence | None:
        """Fetch verified evidence item by ID."""
        with self._lock:
            return self._verified_evidence.get(evidence_id)
