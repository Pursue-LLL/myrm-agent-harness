"""Unit tests for SessionStateDeltaEngine and explicit invalidation protocol.

Validates zero-token unchanged short-circuit, tail delta appending, and explicit invalidation,
benchmarked against DeepSeek Harness 5-step prompt cache protection architecture.
"""

from concurrent.futures import ThreadPoolExecutor

from myrm_agent_harness.runtime.context.session_state_delta_engine import (
    SessionStateDeltaEngine,
)
from myrm_agent_harness.runtime.context.session_state_delta_types import (
    StateMutationKind,
)


def test_initial_state_and_first_turn_delta() -> None:
    """Verifies initial state delta generates correct structured tags and attaches at tail."""
    engine = SessionStateDeltaEngine(
        initial_variables={
            "sandbox_mode": "container",
            "approval_policy": "hitl",
            "cwd": "/workspace",
        }
    )

    delta = engine.compute_turn_delta(turn_index=1)
    assert delta.has_mutations is True
    assert delta.from_revision == 0
    assert delta.to_revision == 1
    assert len(delta.mutations) == 3
    assert all(m.mutation_kind == StateMutationKind.ADDED for m in delta.mutations)
    assert delta.token_delta_estimate > 0

    assert '<session_state_update key="sandbox_mode">container</session_state_update>' in delta.formatted_tail_payload
    assert '<session_state_update key="approval_policy">hitl</session_state_update>' in delta.formatted_tail_payload

    # Attach to tail
    base_prompt = "User prompt: Please analyze the repository."
    stitched = SessionStateDeltaEngine.attach_delta_to_tail(base_prompt, delta)
    assert stitched.startswith(base_prompt)
    assert "<!-- Runtime Session State Delta -->" in stitched
    assert delta.formatted_tail_payload in stitched


def test_zero_token_no_op_when_state_unchanged() -> None:
    """Verifies that an unchanged state results in 0-token injection, preserving prefix cache."""
    engine = SessionStateDeltaEngine(initial_variables={"sandbox_mode": "container"})

    # Turn 1: initial sync
    delta1 = engine.compute_turn_delta(turn_index=1)
    assert delta1.has_mutations is True

    # Turn 2: state remains completely untouched
    delta2 = engine.compute_turn_delta(turn_index=2)
    assert delta2.has_mutations is False
    assert delta2.formatted_tail_payload == ""
    assert delta2.token_delta_estimate == 0
    assert len(delta2.mutations) == 0

    # Attach to tail returns original string unmodified
    base_prompt = "Next user instruction: Run the test suite."
    stitched = SessionStateDeltaEngine.attach_delta_to_tail(base_prompt, delta2)
    assert stitched == base_prompt


def test_state_update_and_explicit_invalidation_notice() -> None:
    """Verifies updated variables and explicitly invalidated variables generate notices."""
    engine = SessionStateDeltaEngine(
        initial_variables={
            "sandbox_mode": "container",
            "approval_policy": "hitl",
        }
    )
    # Turn 1: Sync initial state
    engine.compute_turn_delta(turn_index=1)

    # Mutations for Turn 2:
    # 1. Update approval_policy
    engine.set_variable("approval_policy", "yolo")
    # 2. Invalidate sandbox_mode
    revoked = engine.remove_variable("sandbox_mode", reason="Switched to host execution")
    assert revoked is True
    # 3. Add network_access
    engine.set_variable("network_access", "enabled")

    delta2 = engine.compute_turn_delta(turn_index=2)
    assert delta2.has_mutations is True
    assert len(delta2.mutations) == 3

    kinds = {m.key: m.mutation_kind for m in delta2.mutations}
    assert kinds["approval_policy"] == StateMutationKind.UPDATED
    assert kinds["sandbox_mode"] == StateMutationKind.INVALIDATED
    assert kinds["network_access"] == StateMutationKind.ADDED

    # Verify invalidation tag in payload
    assert (
        '<session_state_invalidated key="sandbox_mode" reason="Switched to host execution" />'
        in delta2.formatted_tail_payload
    )
    assert (
        '<session_state_update key="approval_policy">yolo</session_state_update>'
        in delta2.formatted_tail_payload
    )

    # Check audit log
    history = engine.get_audit_history()
    assert len(history) == 2
    assert history[1].turn_index == 2
    assert "sandbox_mode" in history[1].invalidated_keys


def test_clear_variables_and_full_invalidation() -> None:
    """Verifies clear_variables invalidates all previously active variables."""
    engine = SessionStateDeltaEngine(
        initial_variables={
            "key1": "val1",
            "key2": "val2",
        }
    )
    engine.compute_turn_delta(turn_index=1)

    engine.clear_variables(reason="Session reset requested")
    delta_clear = engine.compute_turn_delta(turn_index=2)
    assert delta_clear.has_mutations is True
    assert len(delta_clear.mutations) == 2
    assert all(m.mutation_kind == StateMutationKind.INVALIDATED for m in delta_clear.mutations)

    # Turn 3: both remain cleared, 0-token no-op again
    delta3 = engine.compute_turn_delta(turn_index=3)
    assert delta3.has_mutations is False
    assert delta3.token_delta_estimate == 0


def test_multithreaded_concurrency_and_audit_integrity() -> None:
    """Verifies thread-safety under concurrent variable mutations and delta computations."""
    engine = SessionStateDeltaEngine(initial_variables={"base_key": "base_val"})
    delta_init = engine.compute_turn_delta(turn_index=0)
    assert delta_init.has_mutations is True

    def _worker(worker_id: int) -> int:
        engine.set_variable(f"worker_{worker_id}", f"val_{worker_id}")
        delta = engine.compute_turn_delta(turn_index=worker_id + 1)
        return delta.token_delta_estimate

    with ThreadPoolExecutor(max_workers=5) as pool:
        estimates = list(pool.map(_worker, range(10)))

    assert len(estimates) == 10
    snapshot = engine.get_active_snapshot()
    assert snapshot.variables["base_key"] == "base_val"
    for i in range(10):
        assert snapshot.variables[f"worker_{i}"] == f"val_{i}"

    audit = engine.get_audit_history()
    assert len(audit) >= 10
