"""Unit tests for explicit state error contracts and zero-hallucination memory prompt guards.

[POS]
tests/test_zero_hallucination_protocol.py
Tests tri-state retrieval assertions, negative prompt guard generation, and storage fault evaluation.

[INPUT]
- myrm_agent_harness.toolkits.memory.zero_hallucination: (
    MemoryFactItem, MemoryRetrievalState, MemoryStateAssertionEvaluator,
    ZeroHallucinationPromptGuard, ZeroHallucinationRetrievalResult
  )

[OUTPUT]
- Test suite verifying 100% defense against silent error-swallowing and model fabrication.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.zero_hallucination import (
    MemoryFactItem,
    MemoryRetrievalState,
    MemoryStateAssertionEvaluator,
    ZeroHallucinationPromptGuard,
)


def test_evaluate_success_with_facts() -> None:
    """Verify that retrieval with facts yields FOUND state and formatted facts."""
    facts = [
        MemoryFactItem(id="f1", text="TypeScript strict mode enabled", category="architecture"),
        MemoryFactItem(id="f2", text="Single file size under 400 lines", category="quality"),
    ]
    res = MemoryStateAssertionEvaluator.evaluate_success(query="coding guidelines", raw_facts=facts)

    assert res.state == MemoryRetrievalState.FOUND
    assert res.total_matched == 2
    assert len(res.facts) == 2
    assert "FOUND (2 facts)" in res.guard_instruction

    wrapped = ZeroHallucinationPromptGuard.wrap_context(res)
    assert "<!-- ZERO_HALLUCINATION_MEMORY_BEGIN -->" in wrapped
    assert "<!-- ZERO_HALLUCINATION_MEMORY_END -->" in wrapped
    assert "TypeScript strict mode enabled" in wrapped


def test_evaluate_success_with_empty_facts() -> None:
    """Verify that retrieval with zero facts yields EXPLICIT_EMPTY with strict anti-hallucination directives."""
    res = MemoryStateAssertionEvaluator.evaluate_success(query="payment secret token", raw_facts=[])

    assert res.state == MemoryRetrievalState.EXPLICIT_EMPTY
    assert res.total_matched == 0
    assert len(res.facts) == 0
    assert "EXPLICIT_EMPTY" in res.guard_instruction
    assert "DO NOT guess, extrapolate, or fabricate" in res.guard_instruction

    wrapped = ZeroHallucinationPromptGuard.wrap_context(res)
    assert "EXPLICIT_EMPTY" in wrapped
    assert "Verified: No past configurations" in wrapped


def test_evaluate_service_error_offline() -> None:
    """Verify that underlying storage failure yields SERVICE_UNAVAILABLE instead of empty list."""
    simulated_error = ConnectionRefusedError("Failed to connect to Qdrant cluster on 127.0.0.1:6333")
    res = MemoryStateAssertionEvaluator.evaluate_service_error(
        query="database url",
        error=simulated_error,
        error_code="VECTOR_STORE_OFFLINE",
    )

    assert res.state == MemoryRetrievalState.SERVICE_UNAVAILABLE
    assert res.error_code == "VECTOR_STORE_OFFLINE"
    assert "Failed to connect to Qdrant" in (res.error_message or "")
    assert "SERVICE_UNAVAILABLE" in res.guard_instruction
    assert "memory retrieval service is currently OFFLINE" in res.guard_instruction

    wrapped = ZeroHallucinationPromptGuard.wrap_context(res)
    assert "SERVICE_UNAVAILABLE" in wrapped


def test_evaluate_partial_degraded() -> None:
    """Verify partial failure retains surviving facts while notifying degradation."""
    surviving = [MemoryFactItem(id="s1", text="User name is Alice", category="profile")]
    degraded = ["vector_qdrant_subsystem"]

    res = MemoryStateAssertionEvaluator.evaluate_partial_degraded(
        query="user profile",
        surviving_facts=surviving,
        degraded_sources=degraded,
    )

    assert res.state == MemoryRetrievalState.PARTIAL_DEGRADED
    assert res.total_matched == 1
    assert res.degraded_sources == ["vector_qdrant_subsystem"]
    assert "PARTIAL_DEGRADED" in res.guard_instruction
    assert "vector_qdrant_subsystem" in res.guard_instruction

    wrapped = ZeroHallucinationPromptGuard.wrap_context(res)
    assert "PARTIAL_DEGRADED" in wrapped
    assert "User name is Alice" in wrapped
