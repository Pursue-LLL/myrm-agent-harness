"""Model switch subagent partitioning barrier and KV cache preservation engine.

[INPUT]
Primary session model bindings, heterogeneous model invocation requests, and execution outputs.

[OUTPUT]
Partitioning interception verdicts, subagent dispatch contracts,
and compact XML-style handshakes preserving primary prefix caches.

[POS]
Item 123 in topic_06 roadmap: eliminates cross-model ping-pong cache eviction in primary sessions.
"""

import threading
import time

from myrm_agent_harness.runtime.context.model_switch_barrier_types import (
    BarrierInterceptionVerdict,
    BarrierRoutingAction,
    CompactCrossModelHandshake,
    OffloadReason,
    PrimarySessionModelLock,
    SubagentDispatchContract,
)


class ModelSwitchSubagentPartitioningBarrier:
    """Barrier safeguarding primary session prefix caches from heterogeneous model mutations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._session_locks: dict[str, PrimarySessionModelLock] = {}
        self._dispatches: dict[str, SubagentDispatchContract] = {}
        self._completed_handshakes: dict[str, CompactCrossModelHandshake] = {}
        self._dispatch_counter: int = 0

    def bind_primary_model(
        self, session_id: str, model_id: str, force_rebind: bool = False
    ) -> PrimarySessionModelLock:
        """Lock primary session to a dedicated model to preserve long prefix KV cache."""
        with self._lock:
            existing = self._session_locks.get(session_id)
            if existing is not None and not force_rebind:
                if existing.bound_model_id != model_id:
                    raise ValueError(
                        f"Session '{session_id}' is already locked to model '{existing.bound_model_id}'. "
                        f"Direct in-place switch to '{model_id}' is prohibited to prevent prefix cache eviction."
                    )
                return existing

            lock = PrimarySessionModelLock(
                session_id=session_id,
                bound_model_id=model_id,
                is_locked=True,
            )
            self._session_locks[session_id] = lock
            return lock

    def get_model_lock(self, session_id: str) -> PrimarySessionModelLock | None:
        """Retrieve model lock for the specified session."""
        with self._lock:
            return self._session_locks.get(session_id)

    def inspect_and_route_request(
        self,
        session_id: str,
        requested_model_id: str,
        offload_reason: OffloadReason,
        instruction: str,
        payload: str,
        current_primary_prefix_tokens: int = 0,
    ) -> BarrierInterceptionVerdict:
        """Inspect inbound request against primary model lock and route accordingly."""
        with self._lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                # Implicitly bind if first request in session
                lock = self.bind_primary_model(session_id, requested_model_id)

            # 1. Matching model: execute natively in primary session
            if lock.bound_model_id == requested_model_id:
                return BarrierInterceptionVerdict(
                    action=BarrierRoutingAction.EXECUTE_ON_PRIMARY,
                    session_id=session_id,
                    bound_model_id=lock.bound_model_id,
                    requested_model_id=requested_model_id,
                    primary_cache_protected=True,
                    dispatch_contract=None,
                    reason="Model matches primary session lock; native execution proceeds without cache eviction.",
                )

            # 2. Heterogeneous model: intercept and offload to isolated subagent
            self._dispatch_counter += 1
            dispatch_id = f"offload_{session_id}_{int(time.time() * 1000)}_{self._dispatch_counter}"
            contract = SubagentDispatchContract(
                dispatch_id=dispatch_id,
                parent_session_id=session_id,
                target_model_id=requested_model_id,
                offload_reason=offload_reason,
                isolated_instruction=instruction,
                input_payload=payload,
                protected_primary_prefix_tokens=current_primary_prefix_tokens,
            )
            self._dispatches[dispatch_id] = contract

            return BarrierInterceptionVerdict(
                action=BarrierRoutingAction.OFFLOAD_TO_ISOLATED_SUBAGENT,
                session_id=session_id,
                bound_model_id=lock.bound_model_id,
                requested_model_id=requested_model_id,
                primary_cache_protected=True,
                dispatch_contract=contract,
                reason=(
                    f"Intercepted in-place switch from '{lock.bound_model_id}' to '{requested_model_id}'. "
                    f"Offloading to isolated subagent '{dispatch_id}' to protect ~{current_primary_prefix_tokens} "
                    f"tokens in primary prefix cache."
                ),
            )

    def compile_compact_handshake(
        self,
        dispatch_contract: SubagentDispatchContract,
        subagent_raw_output: str,
    ) -> CompactCrossModelHandshake:
        """Compile isolated subagent output into a compact append-only envelope."""
        with self._lock:
            cleaned_output = subagent_raw_output.strip()
            compact_tag = (
                f'<heterogeneous_subagent_result '
                f'dispatch_id="{dispatch_contract.dispatch_id}" '
                f'model="{dispatch_contract.target_model_id}" '
                f'reason="{dispatch_contract.offload_reason.value}">\n'
                f"{cleaned_output}\n"
                f"</heterogeneous_subagent_result>"
            )

            handshake = CompactCrossModelHandshake(
                dispatch_id=dispatch_contract.dispatch_id,
                target_model_id=dispatch_contract.target_model_id,
                offload_reason=dispatch_contract.offload_reason,
                summary_result=cleaned_output,
                compact_tag=compact_tag,
                tokens_saved_on_primary_prefix=dispatch_contract.protected_primary_prefix_tokens,
            )
            self._completed_handshakes[dispatch_contract.dispatch_id] = handshake
            return handshake

    def get_total_protected_tokens(self) -> int:
        """Accumulated total count of primary session prefix tokens protected by the barrier."""
        with self._lock:
            return sum(c.protected_primary_prefix_tokens for c in self._dispatches.values())
