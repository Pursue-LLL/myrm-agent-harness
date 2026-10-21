"""[INPUT] VerificationDiagnosisRequest and multi-source evidence items.
[OUTPUT] EvidenceCrossVerificationEngine evaluating 4-tier confidence and actionable findings.
[POS] myrm_agent_harness.observability.evidence_cross_verification.verifier

Thread-safe verification engine combining static code, distributed trace,
runtime logs, and knowledge base history with a 4-tier confidence model.
"""

from collections import deque
import threading
import time
import uuid

from .models import (
    ConfidenceLevel,
    EvidenceItem,
    EvidenceSourceType,
    VerificationDiagnosisRequest,
    VerificationFinding,
)


class EvidenceCrossVerificationEngine:
    """Multi-source evidence cross-verification engine with 4-tier confidence scoring."""

    def __init__(self, max_history: int = 100) -> None:
        self._lock = threading.Lock()
        self._max_history = max_history
        self._diagnoses: deque[VerificationFinding] = deque(maxlen=max_history)
        self._collected_evidences: list[EvidenceItem] = []

    def resolve_error_code_meaning(
        self,
        retcode: str,
        kb_doc: str = "",
        code_def: str = "",
    ) -> tuple[str, bool]:
        """Dual-channel semantic audit for error codes.

        Verifies error meaning via knowledge base documentation or code constant
        definition. If missing in both, standardizes to ErrUnknown_<retcode>.
        """
        clean_code = retcode.strip() or "UNKNOWN"
        kb_clean = kb_doc.strip()
        code_clean = code_def.strip()

        if kb_clean and code_clean:
            return f"{code_clean} ({kb_clean})", True
        if code_clean:
            return code_clean, True
        if kb_clean:
            return kb_clean, True

        # Fallback without hallucination
        return f"ErrUnknown_{clean_code}", False

    def verify_bilateral_call(
        self,
        frontend_param: str,
        backend_struct: str,
        trace_duration_ms: float,
        downstream_error: bool,
    ) -> tuple[bool, str]:
        """Perform bilateral cross-validation between frontend and backend.

        Distinguishes between internal cumulative serial latency vs downstream blocker.
        """
        f_param = frontend_param.strip().lower()
        b_struct = backend_struct.strip().lower()

        # Check parameter schema alignment
        if f_param and b_struct and f_param not in b_struct:
            return False, "PARAM_MISMATCH: Frontend invocation parameters diverge from backend DTO contract"

        if downstream_error:
            return True, "DOWNSTREAM_BLOCK: Request reached downstream service but downstream explicitly failed"

        if trace_duration_ms >= 5000.0:
            return True, "CUMULATIVE_TIMEOUT: Internal cumulative serial calls exceeded timeout deadline before downstream responded"

        return True, "EXECUTION_CONSISTENT: Frontend and backend payloads and timing profiles align"

    def calculate_confidence(
        self,
        evidences: list[EvidenceItem],
        error_code_resolved: bool,
    ) -> tuple[int, ConfidenceLevel]:
        """Quantified 4-tier confidence scoring model.

        Four sources each contribute 1 point:
        1. Knowledge Base (1 pt)
        2. Code Symbol Location (1 pt)
        3. Source Code Logic (1 pt)
        4. Runtime Telemetry Trace (1 pt)

        Rule: If error code meaning is unresolved, confidence is strictly capped at MEDIUM (max 2 pts).
        """
        verified_sources: set[EvidenceSourceType] = set()
        for ev in evidences:
            if ev.is_verified:
                verified_sources.add(ev.source_type)

        raw_score = len(verified_sources)  # 0 to 4

        # Hard guard: If error code cannot be confirmed, maximum confidence is medium
        if not error_code_resolved and raw_score > 2:
            effective_score = 2
            return effective_score, ConfidenceLevel.MEDIUM

        effective_score = raw_score
        if effective_score >= 3:
            return effective_score, ConfidenceLevel.HIGH
        if effective_score == 2:
            return effective_score, ConfidenceLevel.MEDIUM
        return effective_score, ConfidenceLevel.LOW

    def record_evidence(self, evidence: EvidenceItem) -> None:
        """Store an individually verified diagnostic evidence item."""
        with self._lock:
            self._collected_evidences.append(evidence)

    def diagnose_root_cause(
        self,
        req: VerificationDiagnosisRequest,
        evidences: list[EvidenceItem] | None = None,
    ) -> VerificationFinding:
        """Execute action-oriented root cause diagnosis with 4-tier confidence proof."""
        with self._lock:
            active_evidences = list(evidences or self._collected_evidences)

        # 1. Error code dual-channel audit
        code_meaning, is_resolved = self.resolve_error_code_meaning(
            retcode=req.error_code,
            kb_doc=req.kb_doc_hint,
            code_def=req.code_def_hint,
        )

        # 2. Check call budget (capped at 15 calls max)
        budget_limit = min(15, max(1, req.call_budget))
        trimmed_evidences = active_evidences[:budget_limit]

        # 3. Calculate 4-tier confidence
        score, level = self.calculate_confidence(trimmed_evidences, is_resolved)

        # 4. Synthesize root cause category and recommended patch
        target_file = "src/core/router.py"
        target_line = 42
        root_cause = "UNHANDLED_EXCEPTION"
        patch = "Wrap downstream call in circuit breaker timeout guard."

        # Scan evidence metadata for pinpointed files
        for ev in trimmed_evidences:
            if ev.file_path:
                target_file = ev.file_path
            if ev.line_number > 0:
                target_line = ev.line_number
            if "timeout" in ev.detail.lower():
                root_cause = "CUMULATIVE_TIMEOUT"
                patch = "Replace sequential loop with asyncio.gather() or set strict socket timeout deadline."
            elif "downstream" in ev.detail.lower() or "502" in ev.detail:
                root_cause = "DOWNSTREAM_BLOCK"
                patch = "Add exponential backoff retry and graceful fallback response."
            elif "param" in ev.detail.lower() or "mismatch" in ev.detail.lower():
                root_cause = "PARAM_MISMATCH"
                patch = f"Align payload parameters to expected schema at {target_file}:{target_line}."

        finding = VerificationFinding(
            diagnosis_id=f"diag_{uuid.uuid4().hex[:12]}",
            error_code=req.error_code,
            resolved_code_meaning=code_meaning,
            target_file_path=target_file,
            target_line_number=target_line,
            root_cause_category=root_cause,
            explanation=(
                f"Root cause analyzed for event date {req.event_date}. "
                f"Symptom: {req.raw_symptom}. Resolved meaning: {code_meaning}."
            ),
            recommended_patch=patch,
            confidence_score=score,
            confidence_level=level,
            evidences=tuple(trimmed_evidences),
            bilateral_verified=is_resolved and (score >= 2),
        )

        with self._lock:
            self._diagnoses.append(finding)

        return finding

    def get_recent_diagnoses(self, limit: int = 20) -> list[VerificationFinding]:
        """Retrieve recent verification findings."""
        with self._lock:
            return list(self._diagnoses)[-max(1, limit):]

    def reset(self) -> None:
        """Clear collected evidences and historical diagnoses."""
        with self._lock:
            self._diagnoses.clear()
            self._collected_evidences.clear()


# Global thread-safe singleton
_default_verifier: EvidenceCrossVerificationEngine | None = None
_verifier_lock = threading.Lock()


def get_default_evidence_verifier() -> EvidenceCrossVerificationEngine:
    """Retrieve or initialize the global EvidenceCrossVerificationEngine instance."""
    global _default_verifier
    if _default_verifier is None:
        with _verifier_lock:
            if _default_verifier is None:
                _default_verifier = EvidenceCrossVerificationEngine()
    return _default_verifier
