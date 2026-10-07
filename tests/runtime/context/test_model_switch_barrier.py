"""Unit tests for ModelSwitchSubagentPartitioningBarrier and KV cache preservation.

[INPUT]
Primary session locks, matching vs heterogeneous model requests, and mock execution payloads.

[OUTPUT]
Verification of in-place mutation prevention, isolated subagent dispatch contracts,
compact handshake compilation, and thread safety.

[POS]
Quality gate for Item 123 in topic_06 roadmap.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from myrm_agent_harness.runtime.context.model_switch_barrier import (
    ModelSwitchSubagentPartitioningBarrier,
)
from myrm_agent_harness.runtime.context.model_switch_barrier_types import (
    BarrierRoutingAction,
    OffloadReason,
)


def test_bind_primary_model_and_retrieve() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()
    lock = barrier.bind_primary_model("sess_001", "deepseek-chat")
    assert lock.session_id == "sess_001"
    assert lock.bound_model_id == "deepseek-chat"
    assert lock.is_locked is True

    # Idempotent rebind with same model
    rebind = barrier.bind_primary_model("sess_001", "deepseek-chat")
    assert rebind.bound_model_id == "deepseek-chat"

    # Attempting to rebind to different model without force_rebind raises ValueError
    with pytest.raises(ValueError) as exc:
        barrier.bind_primary_model("sess_001", "gpt-4o")
    assert "Direct in-place switch to 'gpt-4o' is prohibited" in str(exc.value)


def test_same_model_execution_no_interception() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()
    barrier.bind_primary_model("sess_main", "deepseek-chat")

    verdict = barrier.inspect_and_route_request(
        session_id="sess_main",
        requested_model_id="deepseek-chat",
        offload_reason=OffloadReason.RATE_LIMIT_ISOLATION,
        instruction="Generate system report",
        payload="source code here",
        current_primary_prefix_tokens=32000,
    )
    assert verdict.action == BarrierRoutingAction.EXECUTE_ON_PRIMARY
    assert verdict.primary_cache_protected is True
    assert verdict.dispatch_contract is None
    assert "native execution proceeds" in verdict.reason


def test_heterogeneous_model_interception_and_subagent_dispatch() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()
    barrier.bind_primary_model("sess_main", "deepseek-chat")

    # Inbound vision request requiring gpt-4o
    verdict = barrier.inspect_and_route_request(
        session_id="sess_main",
        requested_model_id="gpt-4o",
        offload_reason=OffloadReason.VISION_MULTIMODAL,
        instruction="Extract data from architectural diagram image",
        payload="base64_image_bytes...",
        current_primary_prefix_tokens=45000,
    )

    assert verdict.action == BarrierRoutingAction.OFFLOAD_TO_ISOLATED_SUBAGENT
    assert verdict.primary_cache_protected is True
    assert verdict.dispatch_contract is not None

    contract = verdict.dispatch_contract
    assert contract.parent_session_id == "sess_main"
    assert contract.target_model_id == "gpt-4o"
    assert contract.offload_reason == OffloadReason.VISION_MULTIMODAL
    assert contract.protected_primary_prefix_tokens == 45000
    assert "Intercepted in-place switch" in verdict.reason


def test_compile_compact_cross_model_handshake() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()
    barrier.bind_primary_model("sess_main", "deepseek-chat")

    verdict = barrier.inspect_and_route_request(
        session_id="sess_main",
        requested_model_id="gpt-4o",
        offload_reason=OffloadReason.VISION_MULTIMODAL,
        instruction="Inspect diagram",
        payload="img_payload",
        current_primary_prefix_tokens=50000,
    )
    assert verdict.dispatch_contract is not None
    contract = verdict.dispatch_contract

    # Subagent completes isolated task
    raw_subagent_output = "The diagram illustrates a three-tier microkernel with sandboxed workers."
    handshake = barrier.compile_compact_handshake(contract, raw_subagent_output)

    assert handshake.dispatch_id == contract.dispatch_id
    assert handshake.target_model_id == "gpt-4o"
    assert handshake.tokens_saved_on_primary_prefix == 50000
    assert "<heterogeneous_subagent_result" in handshake.compact_tag
    assert f'model="{contract.target_model_id}"' in handshake.compact_tag
    assert f'reason="{contract.offload_reason.value}"' in handshake.compact_tag
    assert "three-tier microkernel" in handshake.compact_tag


def test_accumulated_protected_tokens_counter() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()
    barrier.bind_primary_model("sess_accum", "deepseek-chat")

    barrier.inspect_and_route_request(
        session_id="sess_accum",
        requested_model_id="gpt-4o-mini",
        offload_reason=OffloadReason.CHEAP_SCREENING,
        instruction="Filter spam",
        payload="text",
        current_primary_prefix_tokens=10000,
    )
    barrier.inspect_and_route_request(
        session_id="sess_accum",
        requested_model_id="o1-preview",
        offload_reason=OffloadReason.HEAVY_REASONING,
        instruction="Prove theorem",
        payload="math",
        current_primary_prefix_tokens=25000,
    )

    total_saved = barrier.get_total_protected_tokens()
    assert total_saved == 35000


def test_force_rebind_allowed_with_flag() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()
    barrier.bind_primary_model("sess_reset", "deepseek-chat")
    assert barrier.get_model_lock("sess_reset") is not None

    # Force rebind to claude-3-5-sonnet
    new_lock = barrier.bind_primary_model("sess_reset", "claude-3-5-sonnet", force_rebind=True)
    assert new_lock.bound_model_id == "claude-3-5-sonnet"


def test_thread_safe_concurrent_requests() -> None:
    barrier = ModelSwitchSubagentPartitioningBarrier()

    def worker(worker_id: int) -> bool:
        sid = f"sess_thread_{worker_id}"
        barrier.bind_primary_model(sid, "deepseek-chat")
        # Half requests matching, half requests heterogeneous
        if worker_id % 2 == 0:
            res = barrier.inspect_and_route_request(
                session_id=sid,
                requested_model_id="deepseek-chat",
                offload_reason=OffloadReason.RATE_LIMIT_ISOLATION,
                instruction="query",
                payload="data",
            )
            return res.action == BarrierRoutingAction.EXECUTE_ON_PRIMARY
        else:
            res = barrier.inspect_and_route_request(
                session_id=sid,
                requested_model_id="gpt-4o",
                offload_reason=OffloadReason.VISION_MULTIMODAL,
                instruction="vision",
                payload="image",
                current_primary_prefix_tokens=1000,
            )
            return res.action == BarrierRoutingAction.OFFLOAD_TO_ISOLATED_SUBAGENT

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(worker, i) for i in range(30)]
        results = [f.result() for f in futures]

    assert all(results)
    assert len(barrier._session_locks) == 30
