"""Unit tests for tail-only context append and disambiguated overflow guard.

Verifies:
1. Staging of external messages during execution and strict tail-only checkpoint appending.
2. Invariant verification protecting model provider KV prefix caching.
3. Disambiguation between benign output cap exhaustion and genuine window overflow.
4. One-recovery-per-conversational-input limit preventing infinite loop compaction.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.append_only_compaction_types import (
    ContextEntryRole,
    ContextLogEntry,
)
from myrm_agent_harness.runtime.context.disambiguated_overflow_guard import (
    ConversationalRecoveryGuard,
    LengthOverflowDisambiguator,
)
from myrm_agent_harness.runtime.context.tail_deferred_overflow_types import (
    DeferredWritePriority,
    DisambiguationMetrics,
    StopReasonVerdict,
)
from myrm_agent_harness.runtime.context.tail_deferred_write_queue import (
    TailDeferredWriteQueue,
)


@pytest.fixture
def sample_initial_context() -> list[ContextLogEntry]:
    return [
        ContextLogEntry(
            entry_id="entry_sys_1",
            role=ContextEntryRole.SYSTEM,
            content="You are an autonomous engineering agent.",
            turn_id=0,
        ),
        ContextLogEntry(
            entry_id="entry_user_1",
            role=ContextEntryRole.USER,
            content="Run the integration test suite.",
            turn_id=1,
        ),
        ContextLogEntry(
            entry_id="entry_ast_1",
            role=ContextEntryRole.ASSISTANT,
            content="I will run pytest on tests/.",
            turn_id=1,
        ),
    ]


def test_deferred_write_queue_staging_and_checkpoint_tail_append(
    sample_initial_context: list[ContextLogEntry],
) -> None:
    queue = TailDeferredWriteQueue()
    assert not queue.has_pending()
    assert queue.pending_count() == 0

    # In-flight step: asynchronous messages arrive
    msg1 = queue.stage_deferred(
        role="user",
        content="Slack notification: deployment succeeded.",
        priority=DeferredWritePriority.NORMAL,
        metadata={"source": "slack"},
    )
    msg2 = queue.stage_deferred(
        role="system",
        content="CRITICAL ALERT: Node memory pressure high.",
        priority=DeferredWritePriority.SYSTEM_ALERT,
        metadata={"source": "alertmanager"},
    )

    assert queue.has_pending()
    assert queue.pending_count() == 2
    assert len(queue.peek_pending()) == 2

    # Active context must remain completely untouched during execution
    assert len(sample_initial_context) == 3

    # Checkpoint reached: drain and append strictly at the tail
    updated_context, applied = queue.drain_and_append_at_tail(
        sample_initial_context, turn_id=2
    )

    assert not queue.has_pending()
    assert len(applied) == 2
    # SYSTEM_ALERT has higher priority than NORMAL
    assert applied[0].entry_id == msg2.entry_id
    assert applied[1].entry_id == msg1.entry_id

    # Verify updated context length and order
    assert len(updated_context) == 5
    assert updated_context[0].entry_id == "entry_sys_1"
    assert updated_context[1].entry_id == "entry_user_1"
    assert updated_context[2].entry_id == "entry_ast_1"
    assert updated_context[3].entry_id == msg2.entry_id
    assert updated_context[4].entry_id == msg1.entry_id

    # Invariant: Prefix must be preserved 100%
    assert TailDeferredWriteQueue.validate_tail_only_invariant(
        sample_initial_context, updated_context
    )


def test_invariant_catches_prefix_pollution(
    sample_initial_context: list[ContextLogEntry],
) -> None:
    # 1. Prepended entry violates tail-only invariant
    prepended = [
        ContextLogEntry(
            entry_id="foreign_entry",
            role=ContextEntryRole.SYSTEM,
            content="Injected prefix.",
        ),
        *sample_initial_context,
    ]
    assert not TailDeferredWriteQueue.validate_tail_only_invariant(
        sample_initial_context, prepended
    )

    # 2. Spliced/mutated middle entry violates tail-only invariant
    mutated = list(sample_initial_context)
    mutated[1] = ContextLogEntry(
        entry_id=mutated[1].entry_id,
        role=mutated[1].role,
        content="Altered query.",
    )
    assert not TailDeferredWriteQueue.validate_tail_only_invariant(
        sample_initial_context, mutated
    )


def test_disambiguator_max_tokens_hit_vs_window_overflow() -> None:
    disambiguator = LengthOverflowDisambiguator()

    # Normal stop reasons
    assert (
        disambiguator.disambiguate(
            "stop",
            DisambiguationMetrics(
                actual_output_tokens=150,
                max_output_tokens_budget=2048,
                prompt_tokens=5000,
                model_context_limit=128000,
            ),
        )
        == StopReasonVerdict.NORMAL_STOP
    )

    assert (
        disambiguator.disambiguate(
            "tool_calls",
            DisambiguationMetrics(
                actual_output_tokens=80,
                max_output_tokens_budget=2048,
                prompt_tokens=5000,
                model_context_limit=128000,
            ),
        )
        == StopReasonVerdict.TOOL_USE
    )

    # Finish reason is "length", actual generation hit the requested max budget (e.g. 2048 of 2048)
    # Remaining physical window is ample (128000 - 12048 = 115952)
    # -> Must classify as MAX_OUTPUT_TOKENS_REACHED (no compaction!)
    verdict_budget_hit = disambiguator.disambiguate(
        "length",
        DisambiguationMetrics(
            actual_output_tokens=2047,
            max_output_tokens_budget=2048,
            prompt_tokens=10000,
            model_context_limit=128000,
            output_token_tolerance=2,
        ),
    )
    assert verdict_budget_hit == StopReasonVerdict.MAX_OUTPUT_TOKENS_REACHED

    # Finish reason is "length", but actual generation was severely cut short (e.g. 300 of 4096)
    # or prompt consumed nearly the whole window (127800 + 300 > 128000)
    # -> Must classify as CONTEXT_WINDOW_OVERFLOW (compaction required)
    verdict_window_overflow = disambiguator.disambiguate(
        "length",
        DisambiguationMetrics(
            actual_output_tokens=300,
            max_output_tokens_budget=4096,
            prompt_tokens=127850,
            model_context_limit=128000,
        ),
    )
    assert verdict_window_overflow == StopReasonVerdict.CONTEXT_WINDOW_OVERFLOW


def test_conversational_recovery_guard_one_recovery_limit() -> None:
    guard = ConversationalRecoveryGuard(max_recoveries_per_input=1)
    input_1 = "turn_query_42"
    guard.begin_conversational_cycle(input_1)

    # First overflow in this input cycle: permissible
    verdict1 = guard.check_and_acquire_recovery(input_1)
    assert verdict1.can_recover
    assert verdict1.recovery_attempts == 1

    # Second overflow in the SAME input cycle: circuit breaker triggers!
    verdict2 = guard.check_and_acquire_recovery(input_1)
    assert not verdict2.can_recover
    assert verdict2.recovery_attempts == 1
    assert "Circuit breaker engaged" in verdict2.reason

    # Third overflow: still blocked
    verdict3 = guard.check_and_acquire_recovery(input_1)
    assert not verdict3.can_recover

    # New conversational input turn begins: fresh recovery budget
    input_2 = "turn_query_43"
    guard.begin_conversational_cycle(input_2)

    verdict_new = guard.check_and_acquire_recovery(input_2)
    assert verdict_new.can_recover
    assert verdict_new.recovery_attempts == 1
