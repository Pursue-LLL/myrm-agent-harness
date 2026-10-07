"""ToolLoopTracker: Watchdog detecting tool call oscillation and infinite loops.

Reference: Alibaba Qianwen App Office Mode query2() ToolLoopTracker kernel.
Detects:
1. Direct consecutive identical tool invocations (same name + canonical args).
2. Ping-pong alternating tool oscillations (e.g., A -> B -> A -> B -> A -> B).
3. Persistent consecutive execution failures.
Strict 0 Any, type-hinted, thread-safe.

[INPUT]
- runtime.context.dual_tier_compactor_types::ToolCallSignature, ToolLoopCircuitState (POS: Type definitions
  for Dual-Tier Micro/Full Adaptive Compactor, Mid-Task Steering, and Tool Loop Tracker Watchdog.)

[OUTPUT]
- compute_canonical_args_hash: Compute deterministic SHA-256 hash for tool arguments.
- ToolLoopTracker: Watchdog circuit breaker preventing infinite loops and oscillatory tool usage.

[POS]
ToolLoopTracker: Watchdog detecting tool call oscillation and infinite loops.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping

from .dual_tier_compactor_types import ToolCallSignature, ToolLoopCircuitState


def compute_canonical_args_hash(args: Mapping[str, str | int | float | bool | tuple[str, ...] | list[str]]) -> str:
    """Compute deterministic SHA-256 hash for tool arguments."""
    try:
        # Convert mapping to sort-keyed JSON string
        serialized = json.dumps(dict(args), sort_keys=True, separators=(",", ":"))
    except Exception:
        serialized = str(sorted(args.items()))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]


class ToolLoopTracker:
    """Watchdog circuit breaker preventing infinite loops and oscillatory tool usage."""

    def __init__(
        self,
        max_consecutive_identical: int = 3,
        max_oscillation_cycles: int = 2,
        max_consecutive_errors: int = 3,
    ) -> None:
        self._max_identical = max_consecutive_identical
        self._max_oscillation_cycles = max_oscillation_cycles
        self._max_consecutive_errors = max_consecutive_errors
        self._lock = threading.RLock()
        self._history: list[ToolCallSignature] = []
        self._is_tripped: bool = False
        self._last_state: ToolLoopCircuitState = ToolLoopCircuitState(
            is_tripped=False,
            trip_reason="",
            repeated_count=0,
            tool_name="",
        )

    def record_call(
        self,
        tool_name: str,
        args: Mapping[str, str | int | float | bool | tuple[str, ...] | list[str]],
        is_error: bool = False,
    ) -> ToolLoopCircuitState:
        """Record tool call and inspect whether circuit breaker should trip."""
        with self._lock:
            args_hash = compute_canonical_args_hash(args)
            sig = ToolCallSignature(
                tool_name=tool_name,
                canonical_args_hash=args_hash,
                is_error=is_error,
            )
            self._history.append(sig)

            # 1. Check direct consecutive identical invocations
            identical_count = 0
            for prev in reversed(self._history):
                if (
                    prev.tool_name == sig.tool_name
                    and prev.canonical_args_hash == sig.canonical_args_hash
                ):
                    identical_count += 1
                else:
                    break

            if identical_count >= self._max_identical:
                self._is_tripped = True
                directive = (
                    f"<tool_loop_circuit_breaker tool='{tool_name}' error_type='direct_loop'>\n"
                    f"Warning: Tool '{tool_name}' was invoked {identical_count} times consecutively with identical arguments without making progress.\n"
                    f"Action Required: Stop repeating this tool call! Switch to an alternative tool, adjust parameters, or ask the user for clarification.\n"
                    f"</tool_loop_circuit_breaker>"
                )
                self._last_state = ToolLoopCircuitState(
                    is_tripped=True,
                    trip_reason=f"Identical tool '{tool_name}' called {identical_count} times in a row.",
                    repeated_count=identical_count,
                    tool_name=tool_name,
                    remediation_directive=directive,
                )
                return self._last_state

            # 2. Check alternating ping-pong oscillation (e.g. A, B, A, B, A, B)
            if len(self._history) >= 4:
                oscillation_detected, period = self._detect_oscillation_locked()
                if oscillation_detected:
                    self._is_tripped = True
                    directive = (
                        f"<tool_loop_circuit_breaker tool='{tool_name}' error_type='oscillation'>\n"
                        f"Warning: Alternating tool loop pattern of period {period} detected across {self._max_oscillation_cycles} cycles.\n"
                        f"Action Required: Break the oscillation immediately. Re-evaluate your strategy or query the user.\n"
                        f"</tool_loop_circuit_breaker>"
                    )
                    self._last_state = ToolLoopCircuitState(
                        is_tripped=True,
                        trip_reason=f"Alternating tool oscillation of period {period} detected.",
                        repeated_count=period * self._max_oscillation_cycles,
                        tool_name=tool_name,
                        remediation_directive=directive,
                    )
                    return self._last_state

            # 3. Check persistent failure loop
            consecutive_errors = 0
            for prev in reversed(self._history):
                if prev.tool_name == sig.tool_name and prev.is_error:
                    consecutive_errors += 1
                else:
                    break

            if consecutive_errors >= self._max_consecutive_errors:
                self._is_tripped = True
                directive = (
                    f"<tool_loop_circuit_breaker tool='{tool_name}' error_type='consecutive_errors'>\n"
                    f"Warning: Tool '{tool_name}' failed {consecutive_errors} consecutive times.\n"
                    f"Action Required: Do not attempt this tool again without modified inputs or user intervention.\n"
                    f"</tool_loop_circuit_breaker>"
                )
                self._last_state = ToolLoopCircuitState(
                    is_tripped=True,
                    trip_reason=f"Tool '{tool_name}' failed {consecutive_errors} consecutive times.",
                    repeated_count=consecutive_errors,
                    tool_name=tool_name,
                    remediation_directive=directive,
                )
                return self._last_state

            # Normal healthy execution
            self._last_state = ToolLoopCircuitState(
                is_tripped=False,
                trip_reason="",
                repeated_count=identical_count,
                tool_name=tool_name,
            )
            return self._last_state

    def reset(self) -> None:
        """Reset the loop tracker history and circuit breaker state."""
        with self._lock:
            self._history.clear()
            self._is_tripped = False
            self._last_state = ToolLoopCircuitState(
                is_tripped=False,
                trip_reason="",
                repeated_count=0,
                tool_name="",
            )

    @property
    def is_tripped(self) -> bool:
        """Whether the loop circuit breaker is currently tripped."""
        with self._lock:
            return self._is_tripped

    def get_state(self) -> ToolLoopCircuitState:
        """Get the latest circuit state snapshot."""
        with self._lock:
            return self._last_state

    def _detect_oscillation_locked(self) -> tuple[bool, int]:
        """Detect period-2 and period-3 pattern oscillations."""
        # Check period 2: e.g., A, B, A, B (4 items = 2 cycles), A, B, A, B, A, B (6 items = 3 cycles)
        for period in (2, 3):
            needed_len = period * self._max_oscillation_cycles
            if len(self._history) < needed_len:
                continue

            recent = self._history[-needed_len:]
            pattern = recent[:period]
            matches = True
            for cycle in range(1, self._max_oscillation_cycles):
                sub = recent[cycle * period : (cycle + 1) * period]
                for p_idx in range(period):
                    if (
                        sub[p_idx].tool_name != pattern[p_idx].tool_name
                        or sub[p_idx].canonical_args_hash != pattern[p_idx].canonical_args_hash
                    ):
                        matches = False
                        break
                if not matches:
                    break

            if matches:
                return True, period

        return False, 0
