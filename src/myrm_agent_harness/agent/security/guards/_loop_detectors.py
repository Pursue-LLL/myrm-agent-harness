"""Loop detection algorithms for LoopGuard.

Contains the actual detection logic for each loop pattern. Designed as a
mixin class so that LoopGuard can inherit without tight coupling.

[INPUT]
- loop_guard_types (POS: core types for loop detection)
- loop_suggestions (POS: context-aware suggestion generation)

[OUTPUT]
- LoopDetectorMixin: mixin providing _check_* detection methods

[POS]
Loop detection algorithms — repetition, pattern matching, and stuck-state detection.
LoopGuard delegates detection logic here; this module owns the detection strategies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .loop_guard_types import (
    VERDICT_ALLOW,
    AgentPhase,
    CallRecord,
    LoopAction,
    LoopKind,
    LoopVerdict,
    SuccessLevel,
    get_tool_group,
)
from .loop_suggestions import (
    generate_dynamic_suggestion,
    get_severity_level,
)

if TYPE_CHECKING:
    from collections import deque

    from .loop_guard_types import LoopGuardMetrics

_OUTPUT_TOOL_KEY = "__output__"

_DIMINISHING_HINT = (
    "Output has been very brief for multiple consecutive rounds. "
    "This usually means the task is nearly complete. Please: "
    "(1) review if all requirements are fulfilled, "
    "(2) provide your final summary or response, "
    "or (3) if more work is needed, explain what remains."
)


class LoopDetectorMixin:
    """Mixin providing loop-detection algorithms for LoopGuard.

    Subclass must provide these instance attributes:
    - _window: deque[CallRecord]
    - _metrics: LoopGuardMetrics
    - _warn_threshold, _break_threshold, _pp_cycles, _np_threshold
    - _div_threshold, _dim_threshold, _dim_warn_streak, _dim_break_streak
    - _error_sig_threshold, _poll_tools, _current_phase
    - _output_history: deque[int]
    - _error_signatures: dict[str, int]
    - _last_warning_tool, _last_warning_args_hash, _last_detection_kind
    - _last_suggestion_key, _stats_db
    - _thresholds(tool_name, args) method
    """

    _window: deque[CallRecord]
    _metrics: LoopGuardMetrics
    _warn_threshold: int
    _break_threshold: int
    _pp_cycles: int
    _np_threshold: int
    _div_threshold: int
    _dim_threshold: int
    _dim_warn_streak: int
    _dim_break_streak: int
    _error_sig_threshold: int
    _current_phase: AgentPhase
    _output_history: deque[int]
    _error_signatures: dict[str, int]
    _last_warning_tool: str | None
    _last_warning_args_hash: str | None
    _last_detection_kind: LoopKind | None
    _last_suggestion_key: str | None

    def _thresholds(self, tool_name: str, args: dict[str, object] | None = None) -> tuple[int, int]: ...

    # -------------------------------------------------------------------
    # Detection methods
    # -------------------------------------------------------------------

    def _check_repetition(self, calls: list[CallRecord], tool_name: str, args_hash: str) -> LoopVerdict:
        """Same tool + same args N consecutive times -> WARN or BREAK."""
        streak = 0
        failure_streak = 0
        for i, rec in enumerate(reversed(calls)):
            if rec.tool_name == tool_name and rec.args_hash == args_hash:
                streak += 1
                if i > 0 and rec.success_level == SuccessLevel.FAILURE:
                    failure_streak += 1
            else:
                break

        if streak >= 3 and failure_streak >= 2:
            from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

            self._record_detection(tool_name, LoopKind.REPETITION, streak, args_hash)
            raise ToolStuckException(
                f"TOOL_STUCK_EXCEPTION: 连续 {streak} 次使用相同参数调用工具 '{tool_name}' 且均报错, 强行切断防止死循环。"
            )

        args = calls[-1].args if calls else None
        warn_t, break_t = self._thresholds(tool_name, args)

        if streak >= warn_t:
            self._record_detection(tool_name, LoopKind.REPETITION, streak, args_hash)
            quality_map = {
                key: self._metrics.get_suggestion_quality(key) for key in self._metrics.suggestion_quality_scores
            }
            suggestion = generate_dynamic_suggestion(tool_name, calls, quality_map)
            severity, emoji = get_severity_level(streak)

            if streak >= break_t:
                return LoopVerdict(
                    action=LoopAction.BREAK,
                    reason=f"Tool '{tool_name}' called {streak} times with identical arguments",
                    backoff_hint=f"{emoji} {severity}: {suggestion}",
                    loop_kind=LoopKind.REPETITION.value,
                )
            return LoopVerdict(
                action=LoopAction.WARN,
                reason=(
                    f"{emoji} {severity}: Tool '{tool_name}' called {streak} times consecutively "
                    f"with the same arguments. This appears unproductive — {suggestion}"
                ),
                backoff_hint=suggestion,
                loop_kind=LoopKind.REPETITION.value,
            )

        return VERDICT_ALLOW

    def _check_ping_pong(self, calls: list[CallRecord]) -> LoopVerdict:
        """Two tools + same args alternating A->B->A->B for M cycles."""
        needed = self._pp_cycles * 2
        if len(calls) < needed:
            return VERDICT_ALLOW

        recent = calls[-needed:]
        a_name, a_hash = recent[0].tool_name, recent[0].args_hash
        b_name, b_hash = recent[1].tool_name, recent[1].args_hash

        if a_name == b_name:
            return VERDICT_ALLOW

        for i in range(needed):
            expected_name = a_name if i % 2 == 0 else b_name
            expected_hash = a_hash if i % 2 == 0 else b_hash
            if recent[i].tool_name != expected_name or recent[i].args_hash != expected_hash:
                return VERDICT_ALLOW

        self._record_detection(a_name, LoopKind.PING_PONG, self._pp_cycles)
        return LoopVerdict(
            action=LoopAction.WARN,
            reason=(
                f"Tools '{a_name}' and '{b_name}' are alternating back-and-forth for "
                f"{self._pp_cycles} cycles with identical arguments. "
                "This ping-pong pattern is usually unproductive — try a different strategy."
            ),
            backoff_hint="Break the cycle — try a completely different tool or approach",
            loop_kind=LoopKind.PING_PONG.value,
        )

    def _check_no_progress(self, calls: list[CallRecord], tool_name: str) -> LoopVerdict:
        """Same tool called N times with identical result hashes -> WARN."""
        last = calls[-1]
        if not last.result_hash:
            return VERDICT_ALLOW

        streak = 0
        for rec in reversed(calls):
            if rec.tool_name == last.tool_name and rec.result_hash and rec.result_hash == last.result_hash:
                streak += 1
            else:
                break

        args = last.args
        warn_t, _ = self._thresholds(tool_name, args)
        if streak >= self._np_threshold or streak >= warn_t:
            self._record_detection(tool_name, LoopKind.NO_PROGRESS, streak)
            quality_map = {
                key: self._metrics.get_suggestion_quality(key) for key in self._metrics.suggestion_quality_scores
            }
            suggestion = generate_dynamic_suggestion(tool_name, calls, quality_map)
            severity, emoji = get_severity_level(streak)

            return LoopVerdict(
                action=LoopAction.WARN,
                reason=(
                    f"{emoji} {severity}: Tool '{tool_name}' returned the same result {streak} times in a row. "
                    f"This indicates no progress — {suggestion}"
                ),
                backoff_hint="The tool keeps returning the same result — try a different approach",
                loop_kind=LoopKind.NO_PROGRESS.value,
            )

        return VERDICT_ALLOW

    def _check_output_diminishing(self) -> LoopVerdict:
        """Consecutive rounds with very low LLM output tokens -> WARN or BREAK."""
        history = list(self._output_history)
        if len(history) < self._dim_warn_streak:
            return VERDICT_ALLOW

        if len(history) >= self._dim_break_streak:
            tail = history[-self._dim_break_streak :]
            if all(t < self._dim_threshold for t in tail):
                streak = self._dim_break_streak
                self._record_detection(_OUTPUT_TOOL_KEY, LoopKind.OUTPUT_DIMINISHING, streak)
                severity, emoji = get_severity_level(streak)
                return LoopVerdict(
                    action=LoopAction.BREAK,
                    reason=(f"LLM output has been below {self._dim_threshold} tokens for {streak} consecutive rounds"),
                    backoff_hint=f"{emoji} {severity}: {_DIMINISHING_HINT}",
                    loop_kind=LoopKind.OUTPUT_DIMINISHING.value,
                )

        tail = history[-self._dim_warn_streak :]
        if all(t < self._dim_threshold for t in tail):
            streak = self._dim_warn_streak
            self._record_detection(_OUTPUT_TOOL_KEY, LoopKind.OUTPUT_DIMINISHING, streak)
            severity, emoji = get_severity_level(streak)
            return LoopVerdict(
                action=LoopAction.WARN,
                reason=(
                    f"{emoji} {severity}: LLM output has been below {self._dim_threshold} tokens "
                    f"for {streak} consecutive rounds. {_DIMINISHING_HINT}"
                ),
                backoff_hint=_DIMINISHING_HINT,
                loop_kind=LoopKind.OUTPUT_DIMINISHING.value,
            )

        return VERDICT_ALLOW

    def _check_consecutive_failures(self, calls: list[CallRecord]) -> LoopVerdict:
        """Consecutive tool failures (any tool) N times -> BREAK."""
        past_calls = calls[:-1]
        if len(past_calls) < 3:
            return VERDICT_ALLOW

        failure_streak = 0
        for rec in reversed(past_calls):
            if rec.success_level == SuccessLevel.FAILURE:
                failure_streak += 1
            else:
                break

        if failure_streak >= 3:
            from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

            last_failed_tool = past_calls[-1].tool_name
            self._record_detection(last_failed_tool, LoopKind.CONSECUTIVE_FAILURES, failure_streak)
            raise ToolStuckException(
                f"TOOL_STUCK_EXCEPTION: 连续 {failure_streak} 次工具调用失败, 强行切断防止死循环浪费资源。"
            )

        return VERDICT_ALLOW

    def _check_error_signature(self, tool_name: str, result_text: str) -> LoopVerdict:
        """Cross-tool error signature detection."""
        from .loop_guard import _normalise_error_signature

        sig = _normalise_error_signature(result_text)
        if not sig:
            return VERDICT_ALLOW

        count = self._error_signatures.get(sig, 0) + 1
        self._error_signatures[sig] = count

        if count >= self._error_sig_threshold:
            from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

            self._record_detection(tool_name, LoopKind.ERROR_SIGNATURE, count)
            raise ToolStuckException(
                f"TOOL_STUCK_EXCEPTION: The same error has occurred {count} times "
                f"across tools (signature: {sig[:80]}). Stopping to prevent further waste."
            )

        return VERDICT_ALLOW

    def _check_divergence(self, calls: list[CallRecord]) -> LoopVerdict:
        """Many different tool groups with high failure rate -> WARN."""
        if len(calls) < self._div_threshold:
            return VERDICT_ALLOW

        self._current_phase = self._infer_phase()
        adaptive_threshold = self._current_phase.divergence_failure_threshold

        recent_window = calls[-self._div_threshold :]
        unique_groups = {get_tool_group(rec.tool_name) for rec in recent_window}

        if len(unique_groups) < 4:
            return VERDICT_ALLOW

        failures = sum(1 for rec in recent_window if rec.success_level == SuccessLevel.FAILURE)
        failure_rate = failures / len(recent_window)

        if failure_rate < adaptive_threshold:
            return VERDICT_ALLOW

        unique_tools = {rec.tool_name for rec in recent_window}
        tool_names = ", ".join(sorted(unique_tools)[:5])
        group_names = ", ".join(g.value for g in sorted(unique_groups, key=lambda x: x.value))

        if failure_rate > 0.7:
            severity = "ERROR"
            emoji = ""
            advice = (
                "High failure rate indicates true divergence. "
                "This suggests: (1) clarify the goal and break it into smaller steps, "
                "(2) focus on one approach at a time, or (3) re-evaluate if the task is achievable with current tools."
            )
        else:
            severity = "WARNING"
            emoji = "!"
            advice = (
                "Moderate failure rate suggests partial divergence. "
                "Consider: (1) reviewing which tools succeeded and focus on that approach, "
                "or (2) clarifying the goal before trying more tools."
            )

        first_tool = recent_window[0].tool_name
        self._record_detection(first_tool, LoopKind.DIVERGENCE, len(unique_groups))

        return LoopVerdict(
            action=LoopAction.WARN,
            reason=(
                f"{emoji} {severity}: Tried {len(unique_groups)} different tool categories ({group_names}) "
                f"across {len(unique_tools)} tools ({tool_names}...) "
                f"in the last {self._div_threshold} calls with {failure_rate:.0%} failure rate. "
                f"{advice}"
            ),
            backoff_hint=advice,
            loop_kind=LoopKind.DIVERGENCE.value,
        )

    # -------------------------------------------------------------------
    # Phase inference
    # -------------------------------------------------------------------

    def _infer_phase(self) -> AgentPhase:
        """Infer current agent phase from multi-dimensional patterns."""
        total_calls = self._metrics.total_calls

        if total_calls < 20:
            return AgentPhase.EXPLORATION

        recent_window = list(self._window)[-10:]
        if not recent_window:
            return self._current_phase

        consecutive_failures = 0
        for rec in reversed(recent_window):
            if rec.success_level == SuccessLevel.FAILURE:
                consecutive_failures += 1
            else:
                break

        if consecutive_failures >= 3:
            return AgentPhase.RECOVERY

        consecutive_successes = 0
        for rec in reversed(recent_window):
            if rec.success_level in (
                SuccessLevel.FULL_SUCCESS,
                SuccessLevel.PARTIAL_SUCCESS,
                SuccessLevel.EMPTY_OK,
            ):
                consecutive_successes += 1
            else:
                break

        unique_tools = len({rec.tool_name for rec in recent_window})
        tool_diversity = unique_tools / len(recent_window) if recent_window else 0

        if total_calls < 50:
            if consecutive_successes >= 5 and tool_diversity < 0.3:
                return AgentPhase.EXECUTION
            elif tool_diversity > 0.5:
                return AgentPhase.EXPLORATION
        else:
            if consecutive_successes >= 5 and tool_diversity < 0.4:
                return AgentPhase.EXECUTION
            elif tool_diversity > 0.6:
                return AgentPhase.EXPLORATION

        return self._current_phase

    # -------------------------------------------------------------------
    # Metrics and stats recording
    # -------------------------------------------------------------------

    def _record_detection(self, tool_name: str, kind: LoopKind, streak: int, args_hash: str | None = None) -> None:
        """Update metrics and optionally persist a detection event."""
        self._metrics.total_detections += 1
        self._metrics.detections_by_kind[kind] += 1
        self._metrics.detections_by_tool[tool_name] += 1
        self._metrics.streak_lengths.append(streak)
        self._metrics.suggestions_given += 1
        self._last_warning_tool = tool_name
        self._last_warning_args_hash = args_hash
        self._last_detection_kind = kind
        self._last_suggestion_key = f"{tool_name}:{kind.value}"

        if self._stats_db is not None:
            severity, _ = get_severity_level(streak)
            try:
                last_rec = self._window[-1] if self._window else None
                args_sample = {k: str(v)[:50] for k, v in last_rec.args.items()} if last_rec and last_rec.args else None
                self._stats_db.record_event(
                    tool_name=tool_name,
                    loop_kind=kind,
                    args_sample=args_sample,
                    severity=severity,
                )
            except Exception:
                pass
