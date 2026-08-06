"""Read-only summarize circuit breaker guard for server compaction paths.

[INPUT]
- pipeline.processors.summarize_processor::_is_circuit_open (POS: circuit breaker SSOT)

[OUTPUT]
- is_summarize_circuit_open: whether LLM summarize is temporarily blocked

[POS]
Framework guard export so server ``compact_chat`` respects the same circuit as turn pipeline.
"""

from __future__ import annotations


def is_summarize_circuit_open() -> bool:
    """Return True when consecutive summarize failures have opened the circuit."""
    from myrm_agent_harness.agent.context_management.pipeline.processors.summarize_processor import (
        _is_circuit_open,
    )

    return _is_circuit_open()
