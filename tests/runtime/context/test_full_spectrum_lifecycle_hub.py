"""Unit tests for full-spectrum in-process lifecycle interceptor and dynamic context pruning hub."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.full_spectrum_lifecycle_hub import (
    FullSpectrumLifecycleHub,
)
from myrm_agent_harness.runtime.context.full_spectrum_lifecycle_types import (
    InterceptorAction,
    InterceptorDecision,
    LifecycleEventKind,
    LifecyclePayload,
)
from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
    AgentMessageKind,
)


@pytest.fixture
def hub() -> FullSpectrumLifecycleHub:
    return FullSpectrumLifecycleHub()


def test_input_interception_modify_and_block(hub: FullSpectrumLifecycleHub) -> None:
    """Validate user input rewriting and security rule blocking before inference initiation."""
    # 1. Register a text pre-processor that strips whitespace and prefixes
    def prefix_sanitizer(payload: LifecyclePayload) -> InterceptorDecision:
        original = payload.text or ""
        cleaned = original.strip()
        if cleaned.startswith("/prompt "):
            cleaned = cleaned[len("/prompt ") :]
        modified = LifecyclePayload(
            event_kind=payload.event_kind,
            session_id=payload.session_id,
            turn_index=payload.turn_index,
            text=cleaned,
        )
        return InterceptorDecision(
            action=InterceptorAction.MODIFY,
            modified_payload=modified,
            interceptor_name="prefix_sanitizer",
        )

    hub.register_interceptor(LifecycleEventKind.INPUT, "prefix_sanitizer", prefix_sanitizer, priority=50)

    # 2. Register a security gate that blocks prohibited prompt injection
    def security_gate(payload: LifecyclePayload) -> InterceptorDecision:
        text = payload.text or ""
        if "DROP DATABASE" in text:
            return InterceptorDecision(
                action=InterceptorAction.BLOCK,
                block_reason="Security policy violation: dangerous SQL command rejected",
                interceptor_name="security_gate",
            )
        return InterceptorDecision(action=InterceptorAction.PROCEED)

    hub.register_interceptor(LifecycleEventKind.INPUT, "security_gate", security_gate, priority=100)

    # Case A: Normal sanitized input
    text_out, blocked, reason = hub.intercept_input("sess_1", "  /prompt Explain Dijkstra  ")
    assert not blocked
    assert text_out == "Explain Dijkstra"
    assert reason is None

    # Case B: Blocked input
    text_out2, blocked2, reason2 = hub.intercept_input("sess_1", "DROP DATABASE users;")
    assert text_out2 == "DROP DATABASE users;"
    assert blocked2
    assert reason2 is not None and "Security policy violation" in reason2


def test_before_turn_dynamic_system_prompt_mutation(hub: FullSpectrumLifecycleHub) -> None:
    """Validate per-turn dynamic system prompt and initial turn injection."""
    def preamble_injector(payload: LifecyclePayload) -> InterceptorDecision:
        base_prompt = payload.text or ""
        augmented_prompt = f"{base_prompt}\n[Dynamic Fact: Turn {payload.turn_index} active]"
        new_payload = LifecyclePayload(
            event_kind=payload.event_kind,
            session_id=payload.session_id,
            turn_index=payload.turn_index,
            text=augmented_prompt,
            context_messages=payload.context_messages,
        )
        return InterceptorDecision(
            action=InterceptorAction.MODIFY,
            modified_payload=new_payload,
            interceptor_name="preamble_injector",
        )

    hub.register_interceptor(
        LifecycleEventKind.BEFORE_TURN_START,
        "preamble_injector",
        preamble_injector,
    )

    prompt_res, msgs_res = hub.intercept_before_turn("sess_1", "You are an assistant.", [], turn_index=3)
    assert "[Dynamic Fact: Turn 3 active]" in prompt_res
    assert len(msgs_res) == 0


def test_bash_spawn_hook_env_and_security_gate(hub: FullSpectrumLifecycleHub) -> None:
    """Validate environment variable injection and dangerous command rejection in bash hook."""
    def env_injector(payload: LifecyclePayload) -> InterceptorDecision:
        cur_envs = dict(payload.env_vars or {})
        cur_envs["MYRM_EXEC_MODE"] = "sandboxed"
        new_payload = LifecyclePayload(
            event_kind=payload.event_kind,
            session_id=payload.session_id,
            turn_index=payload.turn_index,
            text=payload.text,
            env_vars=cur_envs,
        )
        return InterceptorDecision(
            action=InterceptorAction.MODIFY,
            modified_payload=new_payload,
            interceptor_name="env_injector",
        )

    def guard_rf_root(payload: LifecyclePayload) -> InterceptorDecision:
        cmd = payload.text or ""
        if "rm -rf /" in cmd:
            return InterceptorDecision(
                action=InterceptorAction.BLOCK,
                block_reason="Destructive command rejected: rm -rf /",
                interceptor_name="guard_rf_root",
            )
        return InterceptorDecision(action=InterceptorAction.PROCEED)

    hub.register_interceptor(LifecycleEventKind.BASH_SPAWN_HOOK, "env_injector", env_injector, priority=50)
    hub.register_interceptor(LifecycleEventKind.BASH_SPAWN_HOOK, "guard_rf_root", guard_rf_root, priority=100)

    # Case A: Valid command gets injected env
    final_cmd, final_envs, is_blk, _ = hub.intercept_bash_spawn("sess_1", "ls -la", {"PATH": "/bin"})
    assert not is_blk
    assert final_cmd == "ls -la"
    assert final_envs["MYRM_EXEC_MODE"] == "sandboxed"

    # Case B: Dangerous command blocked
    _, _, is_blk2, blk_reason = hub.intercept_bash_spawn("sess_1", "rm -rf /var", {})
    assert is_blk2
    assert blk_reason is not None and "Destructive command rejected" in blk_reason


def test_dynamic_context_pruning(hub: FullSpectrumLifecycleHub) -> None:
    """Validate in-process dynamic pruning of noisy context messages."""
    def noisy_debug_filter(payload: LifecyclePayload) -> InterceptorDecision:
        msgs = payload.context_messages or []
        filtered = [m for m in msgs if "NOISY_TRACE" not in m.content]
        new_payload = LifecyclePayload(
            event_kind=payload.event_kind,
            session_id=payload.session_id,
            turn_index=payload.turn_index,
            context_messages=filtered,
        )
        return InterceptorDecision(
            action=InterceptorAction.MODIFY,
            modified_payload=new_payload,
            interceptor_name="noisy_debug_filter",
        )

    hub.register_interceptor(
        LifecycleEventKind.CONTEXT_DYNAMIC_PRUNE,
        "noisy_debug_filter",
        noisy_debug_filter,
    )

    test_msgs = [
        AgentMessage(message_id="m1", kind=AgentMessageKind.USER, content="Hello"),
        AgentMessage(message_id="m2", kind=AgentMessageKind.TOOL_EXECUTION, content="NOISY_TRACE dump"),
        AgentMessage(message_id="m3", kind=AgentMessageKind.ASSISTANT, content="Done"),
    ]

    pruned = hub.intercept_dynamic_context_prune("sess_1", test_msgs)
    assert len(pruned) == 2
    assert [m.message_id for m in pruned] == ["m1", "m3"]


def test_session_before_compact_custom_override(hub: FullSpectrumLifecycleHub) -> None:
    """Validate custom compaction replacement by an extension plugin."""
    def custom_compactor(payload: LifecyclePayload) -> InterceptorDecision:
        compacted = [
            AgentMessage(
                message_id="compacted_summary",
                kind=AgentMessageKind.ASSISTANT,
                content="Custom synthesized checkpoint summary of 10 prior turns",
            )
        ]
        new_payload = LifecyclePayload(
            event_kind=payload.event_kind,
            session_id=payload.session_id,
            turn_index=payload.turn_index,
            context_messages=compacted,
        )
        return InterceptorDecision(
            action=InterceptorAction.REPLACE,
            modified_payload=new_payload,
            interceptor_name="custom_compactor",
        )

    hub.register_interceptor(
        LifecycleEventKind.SESSION_BEFORE_COMPACT,
        "custom_compactor",
        custom_compactor,
    )

    initial_msgs = [
        AgentMessage(message_id=f"msg_{i}", kind=AgentMessageKind.USER, content=f"Step {i}")
        for i in range(10)
    ]
    replaced, result_msgs = hub.intercept_before_compact("sess_1", initial_msgs)
    assert replaced
    assert result_msgs is not None
    assert len(result_msgs) == 1
    assert result_msgs[0].message_id == "compacted_summary"


def test_metrics_and_unregister(hub: FullSpectrumLifecycleHub) -> None:
    """Validate execution metrics tracking and interceptor unregistration."""
    def dummy_interceptor(_: LifecyclePayload) -> InterceptorDecision:
        return InterceptorDecision(action=InterceptorAction.PROCEED)

    hub.register_interceptor(LifecycleEventKind.TURN_END, "dummy_1", dummy_interceptor)
    metrics_before = hub.get_metrics()
    assert metrics_before.registered_interceptors_count >= 1

    unreg_ok = hub.unregister_interceptor(LifecycleEventKind.TURN_END, "dummy_1")
    assert unreg_ok

    metrics_after = hub.get_metrics()
    assert metrics_after.registered_interceptors_count == metrics_before.registered_interceptors_count - 1
