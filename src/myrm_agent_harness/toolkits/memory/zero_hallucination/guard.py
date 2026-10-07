"""Prompt guard injecting unrevocable zero-hallucination directives into LLM context.

[POS]
src/myrm_agent_harness/toolkits/memory/zero_hallucination/guard.py
Formats retrieved facts and injects dual-anchor negative constraints when memory is empty
or services are degraded, making it impossible for the model to hallucinate past preferences.

[INPUT]
- .models: (MemoryRetrievalState, ZeroHallucinationRetrievalResult, MemoryFactItem)

[OUTPUT]
- ZeroHallucinationPromptGuard: Utility building hardened prompt contexts with zero fabrication.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.zero_hallucination.models import (
    MemoryRetrievalState,
    ZeroHallucinationRetrievalResult,
)


class ZeroHallucinationPromptGuard:
    """Constructs prompt context with strict anti-fabrication constraints."""

    @classmethod
    def generate_guard_instruction(cls, result: ZeroHallucinationRetrievalResult) -> str:
        """Create explicit directive matching retrieval state."""
        state = result.state
        query = result.query.strip()

        if state == MemoryRetrievalState.FOUND:
            return (
                f"[MEMORY_STATE: FOUND ({len(result.facts)} facts)] "
                "Historical preferences and context loaded. Adhere strictly to these user facts."
            )

        if state == MemoryRetrievalState.EXPLICIT_EMPTY:
            return (
                f"[MEMORY_STATE: EXPLICIT_EMPTY. Query: \"{query}\"] "
                "Verified: No past configurations, preferences, or rules match this topic in memory. "
                "RULE: You MUST explicitly state that no historical records exist. "
                "DO NOT guess, extrapolate, or fabricate any historical statement."
            )

        if state == MemoryRetrievalState.SERVICE_UNAVAILABLE:
            error_detail = f" ({result.error_code})" if result.error_code else ""
            return (
                f"[MEMORY_STATE: SERVICE_UNAVAILABLE{error_detail}] "
                "The memory retrieval service is currently OFFLINE or unreachable. "
                "RULE: Transparently inform the user that past memories could not be retrieved. "
                "Proceed with current conversation only without assuming any historical configurations."
            )

        if state == MemoryRetrievalState.PARTIAL_DEGRADED:
            sources = ", ".join(result.degraded_sources) if result.degraded_sources else "unknown"
            return (
                f"[MEMORY_STATE: PARTIAL_DEGRADED. Failed sources: {sources}] "
                f"Loaded {len(result.facts)} facts, but some memory indices failed. "
                "Inform the user of partial memory degradation if recalling comprehensive facts."
            )

        # SEARCH_FAILED fallback
        return (
            "[MEMORY_STATE: SEARCH_FAILED] "
            "Memory search operation encountered an unexpected syntax or query parsing error. "
            "Do not pretend past memory exists."
        )

    @classmethod
    def wrap_context(
        cls,
        result: ZeroHallucinationRetrievalResult,
        base_context: str = "",
    ) -> str:
        """Encase base context with defensive boundary directives."""
        guard_directive = cls.generate_guard_instruction(result)

        if result.facts:
            facts_block = "\n".join(
                f"- [{f.category}] {f.text}" for f in result.facts
            )
            base_part = f"\n{base_context.strip()}\n" if base_context.strip() else "\n"
            return (
                f"<!-- ZERO_HALLUCINATION_MEMORY_BEGIN -->\n"
                f"{guard_directive}\n"
                f"{base_part}"
                f"### Retrieved Historical Facts:\n"
                f"{facts_block}\n"
                f"<!-- ZERO_HALLUCINATION_MEMORY_END -->"
            )

        # For EXPLICIT_EMPTY or states with zero facts, emit defensive boundary directives
        return (
            f"<!-- ZERO_HALLUCINATION_MEMORY_BEGIN -->\n"
            f"{guard_directive}\n"
            f"<!-- ZERO_HALLUCINATION_MEMORY_END -->"
        )
