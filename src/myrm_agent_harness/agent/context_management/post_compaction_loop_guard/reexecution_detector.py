# [INPUT]: CompactionBoundaryLedger, LoopDetectionAction, LoopGuardDecision, PostCompactionGuardConfig, RepeatedToolLoopError from tool_loop_types, compute_arguments_hash from compaction_tool_ledger
# [OUTPUT]: ReexecutionDetector
# [POS]: myrm_agent_harness.agent.context_management.post_compaction_loop_guard.reexecution_detector
"""Post-compaction tool re-execution detector and circuit-breaker guard (Item 331).

Inspects tool calls immediately following context compaction against boundary ledger,
injecting soft guidance on initial repeats and deterministically tripping fuses
if repetitive execution loops occur.
"""

from __future__ import annotations

import threading
from typing import Final

from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.compaction_tool_ledger import (
    compute_arguments_hash,
)
from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.tool_loop_types import (
    CompactionBoundaryLedger,
    LoopDetectionAction,
    LoopGuardDecision,
    PostCompactionGuardConfig,
    RepeatedToolLoopError,
)


class ReexecutionDetector:
    """Pre-execution interceptor detecting redundant tool calls across compaction boundaries."""

    def __init__(self, config: PostCompactionGuardConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._config: Final[PostCompactionGuardConfig] = config or PostCompactionGuardConfig()
        # session_id -> CompactionBoundaryLedger
        self._ledgers: dict[str, CompactionBoundaryLedger] = {}
        # (session_id, args_hash) -> repeat_count
        self._repeat_counts: dict[tuple[str, str], int] = {}

    @property
    def config(self) -> PostCompactionGuardConfig:
        """Active detection configuration."""
        return self._config

    def register_boundary_ledger(self, ledger: CompactionBoundaryLedger) -> None:
        """Register newly captured compaction boundary ledger for session."""
        with self._lock:
            self._ledgers[ledger.session_id] = ledger
            # Reset repeat counters for this session across fresh compaction
            keys_to_remove = [k for k in self._repeat_counts if k[0] == ledger.session_id]
            for k in keys_to_remove:
                self._repeat_counts.pop(k, None)

    def evaluate_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, str | int | float | bool | list[str] | dict[str, str] | None] | str,
        current_turn: int,
        raise_on_trip: bool = False,
    ) -> LoopGuardDecision:
        """Evaluate upcoming tool execution against the active boundary ledger.

        Args:
            session_id: Conversation session identifier.
            tool_name: Name of tool to be called.
            arguments: Tool call arguments payload.
            current_turn: Current turn counter in the conversation.
            raise_on_trip: Whether to immediately raise RepeatedToolLoopError if tripped.

        Returns:
            LoopGuardDecision with action verdict and reminder message.
        """
        args_hash, canonical_json = compute_arguments_hash(tool_name, arguments)

        with self._lock:
            ledger = self._ledgers.get(session_id)
            if not ledger:
                # No boundary ledger active for this session
                return LoopGuardDecision(
                    action=LoopDetectionAction.ALLOW,
                    tool_name=tool_name,
                    arguments_hash=args_hash,
                    repeat_count=0,
                    injected_reminder="",
                    is_circuit_broken=False,
                )

            # Check if within protected window turns
            turns_since_compaction = current_turn - ledger.compaction_turn_index
            if turns_since_compaction < 0 or turns_since_compaction > self._config.protect_window_turns:
                return LoopGuardDecision(
                    action=LoopDetectionAction.ALLOW,
                    tool_name=tool_name,
                    arguments_hash=args_hash,
                    repeat_count=0,
                    injected_reminder="",
                    is_circuit_broken=False,
                )

            # Match against ledger signatures
            matched_signature = next(
                (sig for sig in ledger.signatures if sig.arguments_hash == args_hash),
                None,
            )

            if not matched_signature:
                return LoopGuardDecision(
                    action=LoopDetectionAction.ALLOW,
                    tool_name=tool_name,
                    arguments_hash=args_hash,
                    repeat_count=0,
                    injected_reminder="",
                    is_circuit_broken=False,
                )

            # Matched a tool call that already completed before compaction!
            key = (session_id, args_hash)
            current_count = self._repeat_counts.get(key, 0) + 1
            self._repeat_counts[key] = current_count

            # 1. Hard Trip Threshold
            if current_count >= self._config.hard_trip_threshold:
                err_msg = (
                    f"CRITICAL: Tool '{tool_name}' was repeatedly called {current_count} times with identical "
                    f"parameters immediately after context compaction (boundary turn {ledger.compaction_turn_index}). "
                    f"Prior result was '{matched_signature.result_digest}'. Circuit breaker tripped to prevent token burning."
                )
                if raise_on_trip:
                    raise RepeatedToolLoopError(
                        tool_name=tool_name,
                        args_hash=args_hash,
                        repeat_count=current_count,
                        message=err_msg,
                    )

                return LoopGuardDecision(
                    action=LoopDetectionAction.TRIPPED_CIRCUIT_BREAKER,
                    tool_name=tool_name,
                    arguments_hash=args_hash,
                    repeat_count=current_count,
                    injected_reminder=err_msg,
                    is_circuit_broken=True,
                )

            # 2. Soft Remind Threshold
            if current_count >= self._config.soft_remind_threshold:
                reminder = (
                    f"[SYSTEM NOTICE: TOOL ALREADY EXECUTED] The tool invocation '{tool_name}' with parameters "
                    f"{canonical_json} was already successfully executed prior to this compaction boundary. "
                    f"Result: '{matched_signature.result_digest}'. "
                    "Synthesize your plan using this existing outcome rather than redundantly re-executing."
                )
                return LoopGuardDecision(
                    action=LoopDetectionAction.REMIND_IN_CONTEXT,
                    tool_name=tool_name,
                    arguments_hash=args_hash,
                    repeat_count=current_count,
                    injected_reminder=reminder,
                    is_circuit_broken=False,
                )

            return LoopGuardDecision(
                action=LoopDetectionAction.ALLOW,
                tool_name=tool_name,
                arguments_hash=args_hash,
                repeat_count=current_count,
                injected_reminder="",
                is_circuit_broken=False,
            )

    def get_repeat_count(self, session_id: str, args_hash: str) -> int:
        """Query repeat count for specific tool arguments."""
        with self._lock:
            return self._repeat_counts.get((session_id, args_hash), 0)

    def reset_session(self, session_id: str) -> None:
        """Evict ledger and tracking counters for session."""
        with self._lock:
            self._ledgers.pop(session_id, None)
            keys_to_remove = [k for k in self._repeat_counts if k[0] == session_id]
            for k in keys_to_remove:
                self._repeat_counts.pop(k, None)
