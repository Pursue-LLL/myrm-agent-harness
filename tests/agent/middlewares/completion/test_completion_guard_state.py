"""Unit tests for the per-turn guard state and disclosure registry."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
    set_current_message_id,
)
from myrm_agent_harness.agent.middlewares.completion import completion_guard_state as state_mod
from myrm_agent_harness.agent.security.guards.loop_guard import (
    CallRecord,
    SuccessLevel,
    VerificationCategory,
)


@pytest.fixture(autouse=True)
def _bound_unbound_key():
    """Every test runs on the unbound key unless it sets one explicitly."""
    set_current_message_id("")
    yield
    set_current_message_id("")
    state_mod.reset_run_state()


def _bound(message_id: str):
    set_current_message_id(message_id)


def _test_record() -> CallRecord:
    record = CallRecord(
        tool_name="bash_code_execute_tool",
        args_hash="hash",
        args={"command": "pytest -q"},
        result_content="236 passed in 12.4s",
        success_level=SuccessLevel.FULL_SUCCESS,
    )
    record.verification_type = VerificationCategory.TEST
    return record


def test_run_key_falls_back_to_the_unbound_key() -> None:
    assert state_mod.run_key() == state_mod.UNBOUND_RUN_KEY


def test_current_run_state_is_cached_per_turn() -> None:
    first = state_mod.current_run_state()
    first.rejections = 2
    assert state_mod.current_run_state().rejections == 2

    _bound("msg-other")
    assert state_mod.current_run_state().rejections == 0

    _bound("")
    assert state_mod.current_run_state().rejections == 2


def test_reset_run_state_drops_state_and_disclosure() -> None:
    state_mod.current_run_state().rejections = 1
    state_mod.publish_disclosure(deliverable_tier={"tier": "PLAN"})

    state_mod.reset_run_state()

    assert state_mod.current_run_state().rejections == 0
    assert state_mod.pop_run_disclosure("") is None


def test_state_registry_evicts_oldest_turns_beyond_the_cap() -> None:
    assert state_mod.RUN_STATE_LIMIT > 0
    for index in range(state_mod.RUN_STATE_LIMIT + 1):
        _bound(f"msg-{index}")
        state_mod.current_run_state()

    assert len(state_mod._run_states) == state_mod.RUN_STATE_LIMIT
    assert "msg-0" not in state_mod._run_states
    assert f"msg-{state_mod.RUN_STATE_LIMIT}" in state_mod._run_states

    for index in range(state_mod.RUN_STATE_LIMIT + 1):
        _bound(f"msg-{index}")
        state_mod.reset_run_state()


def test_publish_disclosure_keeps_latest_values_and_trims() -> None:
    state_mod.publish_disclosure(deliverable_tier={"tier": "PLAN"}, staged_artifacts=[{"filename": "a.py"}])
    state_mod.publish_disclosure(deliverable_tier={"tier": "ARTIFACT"})

    entry = state_mod.pop_run_disclosure("")
    assert entry is not None
    assert entry["deliverable_tier"] == {"tier": "ARTIFACT"}
    assert entry["staged_artifacts"] == [{"filename": "a.py"}]
    assert state_mod.pop_run_disclosure("") is None

    for index in range(state_mod.RUN_STATE_LIMIT + 1):
        _bound(f"msg-{index}")
        state_mod.publish_disclosure(deliverable_tier={"tier": "PLAN"})
        state_mod.reset_run_state()


def test_publish_tier_disclosure_respects_content_and_policy() -> None:
    state_mod.publish_tier_disclosure("", [_test_record()], has_claim=True)
    assert state_mod.pop_run_disclosure("") is None

    state_mod.publish_tier_disclosure("一切就绪。", [_test_record()], has_claim=True)
    entry = state_mod.pop_run_disclosure("")
    assert entry is not None
    assert entry["deliverable_tier"]["tier"] == "VERIFIED"

    state_mod.publish_tier_disclosure("一切就绪。", [], has_claim=False)
    assert state_mod.pop_run_disclosure("") is None


def test_attach_disclosure_to_event_is_a_noop_without_payload() -> None:
    event: dict[str, object] = {"type": "message_end"}

    state_mod.attach_disclosure_to_event(event, "")

    assert event == {"type": "message_end"}


def test_attach_disclosure_to_event_writes_payload_once() -> None:
    _bound("msg-attach")
    state_mod.publish_disclosure(
        deliverable_tier={"tier": "ARTIFACT"},
        staged_artifacts=[{"filename": "draft.py"}],
    )
    event: dict[str, object] = {"type": "message_end"}

    state_mod.attach_disclosure_to_event(event, "msg-attach")
    assert event["deliverable_tier"] == {"tier": "ARTIFACT"}
    assert event["staged_artifacts"] == [{"filename": "draft.py"}]

    second: dict[str, object] = {"type": "message_end"}
    state_mod.attach_disclosure_to_event(second, "msg-attach")
    assert "deliverable_tier" not in second


def test_attach_falls_back_to_the_unbound_slot_when_keys_diverge() -> None:
    """A resumed or re-entered cycle can bind no turn id while the emitter knows one."""
    state_mod.publish_disclosure(deliverable_tier={"tier": "ARTIFACT"})
    event: dict[str, object] = {"type": "message_end"}

    state_mod.attach_disclosure_to_event(event, "msg-known-to-the-emitter")

    assert event["deliverable_tier"] == {"tier": "ARTIFACT"}
    assert state_mod.pop_run_disclosure("") is None
    assert state_mod.pop_run_disclosure("msg-known-to-the-emitter") is None


def test_record_evidence_accumulates_and_dedupes_within_a_turn() -> None:
    record = _test_record()

    first = state_mod.record_evidence([record])
    second = state_mod.record_evidence([record])

    assert len(first) == 1
    assert second is first
    assert len(second) == 1

    _bound("msg-other")
    other_ledger = state_mod.record_evidence([record])
    assert other_ledger is not second
    assert len(other_ledger) == 1
    state_mod.reset_run_state()
    _bound("")
    state_mod.reset_run_state()
