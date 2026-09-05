"""Unit tests for SubtaskPhaseTaggedEpisodicMemoryPack.

Validates:
1. EpisodicMemory schema enhancements (subtask_phase, is_failure_attempt, failure_reason, negative_lesson).
2. Memory context formatting with Failed Attempts & Negative Traps section.
3. Subtask phase memories partition and prompt cache safety.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares.memory_context.memory_context_format import (
    _format_memory_context,
)
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryType


def test_episodic_memory_subtask_phase_fields_default() -> None:
    ep = EpisodicMemory(content="Analyzed memory context")
    assert ep.memory_type == MemoryType.EPISODIC
    assert ep.subtask_phase is None
    assert ep.is_failure_attempt is False
    assert ep.failure_reason is None
    assert ep.negative_lesson is None


def test_episodic_memory_subtask_phase_failure_fields() -> None:
    ep = EpisodicMemory(
        content="Attempted to use sync sqlite in async loop",
        subtask_phase="edit",
        is_failure_attempt=True,
        failure_reason="BlockingIOError: cannot run synchronous connection in async event loop",
        negative_lesson="Always use aiosqlite or run_in_executor for SQLite access in async services",
    )
    assert ep.subtask_phase == "edit"
    assert ep.is_failure_attempt is True
    assert "BlockingIOError" in (ep.failure_reason or "")
    assert "Always use aiosqlite" in (ep.negative_lesson or "")


def test_memory_context_format_renders_failure_traps() -> None:
    learned = {
        "learned_episodes": [
            {
                "content": "Tried updating auth middleware with raw IP bypass",
                "subtask_phase": "verify",
                "is_failure_attempt": True,
                "failure_reason": "DNS rebinding exploit succeeded",
                "negative_lesson": "Never bypass host header validation without loopback check",
            },
            {
                "content": "Located token refresh route in auth_router.py",
                "subtask_phase": "locate",
                "is_failure_attempt": False,
            },
        ]
    }
    ctx: dict[str, object] = {}
    stable, untrusted = _format_memory_context(ctx, learned, memory_search_enabled=False)

    assert untrusted is not None
    assert "Failed Attempts & Negative Traps (Do not repeat)" in untrusted
    assert "[VERIFY] Tried updating auth middleware with raw IP bypass" in untrusted
    assert "Cause: DNS rebinding exploit succeeded" in untrusted
    assert "AVOID: Never bypass host header validation without loopback check" in untrusted
    assert "Subtask Phase Memories" in untrusted
    assert "[LOCATE] Located token refresh route in auth_router.py" in untrusted
