"""State assertion evaluator preventing silent error-swallowing in memory queries.

[POS]
src/myrm_agent_harness/toolkits/memory/zero_hallucination/evaluator.py
Analyzes raw retrieval responses, exceptions, and partial failure states to deterministically
produce ZeroHallucinationRetrievalResult with exact state categorizations.

[INPUT]
- .models: (MemoryRetrievalState, ZeroHallucinationRetrievalResult, MemoryFactItem)
- .guard: ZeroHallucinationPromptGuard

[OUTPUT]
- MemoryStateAssertionEvaluator: Engine converting memory responses into strict zero-hallucination results.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.zero_hallucination.guard import (
    ZeroHallucinationPromptGuard,
)
from myrm_agent_harness.toolkits.memory.zero_hallucination.models import (
    MemoryFactItem,
    MemoryRetrievalState,
    ZeroHallucinationRetrievalResult,
)


class MemoryStateAssertionEvaluator:
    """Evaluates raw query returns or faults into explicit tri-state assertions."""

    @classmethod
    def evaluate_success(
        cls,
        query: str,
        raw_facts: list[MemoryFactItem],
    ) -> ZeroHallucinationRetrievalResult:
        """Evaluate successful query output into FOUND or EXPLICIT_EMPTY."""
        clean_facts = [f for f in raw_facts if f.text.strip()]
        if clean_facts:
            res = ZeroHallucinationRetrievalResult(
                state=MemoryRetrievalState.FOUND,
                query=query,
                facts=clean_facts,
                total_matched=len(clean_facts),
            )
            return ZeroHallucinationRetrievalResult(
                state=res.state,
                query=res.query,
                facts=res.facts,
                total_matched=res.total_matched,
                guard_instruction=ZeroHallucinationPromptGuard.generate_guard_instruction(res),
            )

        empty_res = ZeroHallucinationRetrievalResult(
            state=MemoryRetrievalState.EXPLICIT_EMPTY,
            query=query,
            facts=[],
            total_matched=0,
        )
        return ZeroHallucinationRetrievalResult(
            state=empty_res.state,
            query=empty_res.query,
            facts=empty_res.facts,
            total_matched=empty_res.total_matched,
            guard_instruction=ZeroHallucinationPromptGuard.generate_guard_instruction(empty_res),
        )

    @classmethod
    def evaluate_service_error(
        cls,
        query: str,
        error: Exception | str,
        error_code: str = "STORAGE_OFFLINE",
    ) -> ZeroHallucinationRetrievalResult:
        """Convert underlying storage failure into explicit SERVICE_UNAVAILABLE assertion."""
        error_msg = str(error)
        res = ZeroHallucinationRetrievalResult(
            state=MemoryRetrievalState.SERVICE_UNAVAILABLE,
            query=query,
            facts=[],
            total_matched=0,
            error_code=error_code,
            error_message=error_msg,
        )
        return ZeroHallucinationRetrievalResult(
            state=res.state,
            query=res.query,
            facts=res.facts,
            total_matched=res.total_matched,
            error_code=res.error_code,
            error_message=res.error_message,
            guard_instruction=ZeroHallucinationPromptGuard.generate_guard_instruction(res),
        )

    @classmethod
    def evaluate_partial_degraded(
        cls,
        query: str,
        surviving_facts: list[MemoryFactItem],
        degraded_sources: list[str],
    ) -> ZeroHallucinationRetrievalResult:
        """Convert partial multi-source failure into PARTIAL_DEGRADED assertion."""
        clean_facts = [f for f in surviving_facts if f.text.strip()]
        res = ZeroHallucinationRetrievalResult(
            state=MemoryRetrievalState.PARTIAL_DEGRADED,
            query=query,
            facts=clean_facts,
            total_matched=len(clean_facts),
            degraded_sources=degraded_sources,
        )
        return ZeroHallucinationRetrievalResult(
            state=res.state,
            query=res.query,
            facts=res.facts,
            total_matched=res.total_matched,
            degraded_sources=res.degraded_sources,
            guard_instruction=ZeroHallucinationPromptGuard.generate_guard_instruction(res),
        )
