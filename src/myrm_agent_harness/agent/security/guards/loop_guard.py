"""LoopGuard — unified inefficiency detection for Agent sessions.

Detects five categories of low-efficiency patterns and provides
context-aware, priority-sorted suggestions to help the LLM self-correct:

1. **Repetition** — same tool + same args called N consecutive times
2. **Ping-pong** — two tools alternating A->B->A->B with same args for M cycles
3. **No-progress** — same tool returning identical results N times
4. **Divergence** — rapid tool-group switching (4+ groups) with high failure rate,
   adaptive threshold based on agent phase (Exploration 60% / Execution 30% / Recovery 15%)
5. **Output diminishing** — LLM output tokens consistently low across consecutive rounds,
   indicating the model has little substantive work left

Iteration budget:
- Budget thresholds (warn / critical / stuck) are dynamically derived from
  ``graph_recursion_limit`` via ``_configure_budget``, converting graph nodes
  to tool calls using ``_NODES_PER_TOOL_CALL``.

Response levels:
- WARN (streak 3-4): append warning + smart suggestion to ToolMessage
- BREAK (streak 5+): block execution entirely (prevent resource waste)
- Severity: WARNING (3-5x) -> ERROR (6-9x) -> CRITICAL (10+x)

[INPUT]
- loop_guard_types (POS: core types for loop detection)
- loop_suggestions (POS: context-aware suggestion generation)
- _loop_detectors (POS: detection algorithm mixin)
- loop_guard_stats (POS: optional persistent statistics, lazy import)

[OUTPUT]
- LoopGuard: session-scoped detector with BREAK/WARN/ALLOW verdicts,
  loop pattern metadata, smart suggestions, metrics, and quality feedback

[POS]
Session-level safety guard integrated into tool_interceptor_middleware.
Pre-call: detect loops (incl. output diminishing) and optionally BREAK execution.
Post-call: record results for no-progress detection and suggestion tracking.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque

from ._loop_detectors import LoopDetectorMixin
from .loop_guard_types import (
    VERDICT_ALLOW,
    AgentPhase,
    CallRecord,
    LoopAction,
    LoopGuardMetrics,
    LoopKind,
    LoopVerdict,
    SuccessLevel,
    VerificationCategory,
)
from .loop_suggestions import evaluate_success_level

try:
    from .loop_guard_stats import LoopGuardStatsDB
except ImportError:
    LoopGuardStatsDB = None  # type: ignore[assignment, misc]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _stable_hash(obj: object) -> str:
    """Deterministic hash of a JSON-serialisable object (truncated to 16 hex chars)."""
    raw = json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _result_hash(tool_name: str, result_text: str) -> str:
    """SHA-256 of tool_name + result content (first 4096 chars)."""
    payload = f"{tool_name}:{result_text[:4096]}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


_LINE_NUM_RE = re.compile(r"\bline\s+\d+\b", re.IGNORECASE)
_ABS_PATH_RE = re.compile(r"(?:/[\w./-]+|[A-Z]:\\[\w.\\-]+)")
_WS_RE = re.compile(r"\s+")


def _normalise_error_signature(result_text: str) -> str:
    """Derive a stable error signature from tool result text.

    Strips variable parts (line numbers, absolute paths, extra whitespace)
    so that ``SyntaxError: unexpected character (line 32)`` and
    ``SyntaxError: unexpected character (line 42)`` produce the same key.
    Only the first ``ToolExecutionError:`` line is used.
    """
    for line in result_text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("ToolExecutionError:"):
            core = stripped[len("ToolExecutionError:") :].strip()
            break
    else:
        core = result_text[:200]

    core = _LINE_NUM_RE.sub("line N", core)
    core = _ABS_PATH_RE.sub("<path>", core)
    core = _WS_RE.sub(" ", core).strip().lower()
    return core[:120]


# ---------------------------------------------------------------------------
# LoopGuard
# ---------------------------------------------------------------------------


class LoopGuard(LoopDetectorMixin):
    """Session-scoped inefficiency detector with smart suggestions.

    Parameters
    ----------
    window_size:
        How many recent calls to keep in the sliding window.
    warn_threshold:
        Consecutive identical calls to trigger WARN.
    break_threshold:
        Consecutive identical calls to trigger BREAK (block execution).
    ping_pong_cycles:
        Number of A->B alternation cycles to flag as ping-pong.
    no_progress_threshold:
        Consecutive calls with identical results to flag as no-progress.
    divergence_threshold:
        Number of calls to examine for divergence detection.
    diminishing_threshold:
        Output tokens below this value are considered "very brief".
    diminishing_warn_streak:
        Consecutive brief outputs to trigger WARN.
    diminishing_break_streak:
        Consecutive brief outputs to trigger BREAK.
    error_signature_threshold:
        Cross-tool same-error repetitions before ToolStuckException.
    graph_recursion_limit:
        LangGraph ``recursion_limit``; used to derive iteration budget
        thresholds (warn / critical / stuck) via ``_configure_budget``.
    poll_tools:
        Tool names with relaxed thresholds (2x normal).
    stats_db:
        Optional persistent statistics database.
    enable_stats:
        Whether to enable persistent statistics collection.
    """

    _NODES_PER_TOOL_CALL = 3

    def __init__(
        self,
        *,
        window_size: int = 20,
        warn_threshold: int = 3,
        break_threshold: int = 5,
        ping_pong_cycles: int = 3,
        no_progress_threshold: int = 4,
        divergence_threshold: int = 6,
        diminishing_threshold: int = 500,
        diminishing_warn_streak: int = 2,
        diminishing_break_streak: int = 3,
        error_signature_threshold: int = 5,
        graph_recursion_limit: int = 100,
        poll_tools: frozenset[str] = frozenset(),
        stats_db: LoopGuardStatsDB | None = None,
        enable_stats: bool = False,
    ) -> None:
        self._window: deque[CallRecord] = deque(maxlen=window_size)
        self._warn_threshold = warn_threshold
        self._break_threshold = break_threshold
        self._pp_cycles = ping_pong_cycles
        self._np_threshold = no_progress_threshold
        self._div_threshold = divergence_threshold
        self._dim_threshold = diminishing_threshold
        self._dim_warn_streak = diminishing_warn_streak
        self._dim_break_streak = diminishing_break_streak
        self._error_sig_threshold = error_signature_threshold
        self._poll_tools = poll_tools
        self._metrics = LoopGuardMetrics()
        self._last_warning_tool: str | None = None
        self._last_warning_args_hash: str | None = None
        self._pending_follow_check: bool = False
        self._current_phase: AgentPhase = AgentPhase.EXPLORATION
        self._last_suggestion_key: str | None = None
        self._last_detection_kind: LoopKind | None = None
        self._output_history: deque[int] = deque(maxlen=window_size)
        self._last_recorded_call_index: int = -1
        self._error_signatures: dict[str, int] = {}
        self._stats_db = stats_db if enable_stats else None
        if enable_stats and stats_db is None and LoopGuardStatsDB is not None:
            self._stats_db = LoopGuardStatsDB()

        self._configure_budget(graph_recursion_limit)

    def _configure_budget(self, graph_recursion_limit: int) -> None:
        """Compute tool-call budget thresholds from the graph recursion limit.

        Guarantees the strict ordering ``warn < critical < stuck <= tool_budget``
        even for very small recursion limits.
        """
        tool_budget = graph_recursion_limit // self._NODES_PER_TOOL_CALL
        stuck = min(max(tool_budget - 1, 3), tool_budget)
        critical = min(max(tool_budget * 9 // 10, 2), stuck - 1)
        warn = min(max(tool_budget * 7 // 10, 1), critical - 1)
        self._budget_warn = warn
        self._budget_critical = critical
        self._budget_stuck = stuck

    def _thresholds(self, tool_name: str, args: dict[str, object] | None = None) -> tuple[int, int]:
        """Return (warn, break) thresholds, relaxed 2x for poll/idempotent tools."""
        from myrm_agent_harness.agent.security.tool_registry import (
            resolve_safety_metadata,
        )

        is_idempotent = False

        safety_meta = resolve_safety_metadata(tool_name)
        if safety_meta.is_idempotent:
            is_idempotent = True

        if not is_idempotent and tool_name == "bash_code_execute_tool" and args:
            command = str(args.get("command", "")).strip()
            if command.startswith(("ls ", "cat ", "grep ", "find ", "pwd", "echo ", "head ", "tail ")):
                is_idempotent = True

        if tool_name in self._poll_tools or is_idempotent:
            return self._warn_threshold * 2, self._break_threshold * 2
        return self._warn_threshold, self._break_threshold

    def feed_output_tokens(self, call_index: int, tokens: int, *, has_tool_call: bool = False) -> None:
        """Record LLM output token count for diminishing returns detection.

        When ``has_tool_call`` is True the tokens are *not* appended to
        ``_output_history`` because short completion tokens are **normal**
        when the LLM emits a tool call (the bulk of the output is the
        structured function invocation, not free-form text).  Only
        text-only LLM rounds feed the diminishing-output detector.
        """
        if call_index <= self._last_recorded_call_index:
            return
        self._last_recorded_call_index = call_index
        if not has_tool_call:
            self._output_history.append(tokens)

    def pre_check(self, tool_name: str, args: dict[str, object]) -> LoopVerdict:
        """Check for inefficiency patterns before executing a tool call."""
        self._metrics.total_calls += 1
        args_hash = _stable_hash(args)

        if self._last_warning_tool is not None:
            param_changed = tool_name == self._last_warning_tool and self._last_warning_args_hash != args_hash
            if param_changed:
                self._metrics.suggestions_followed += 1
                self._pending_follow_check = True
            self._last_warning_tool = None
            self._last_warning_args_hash = None

        rec = CallRecord(tool_name=tool_name, args_hash=args_hash, args=args)
        self._window.append(rec)

        calls = list(self._window)
        if len(calls) < 2:
            return VERDICT_ALLOW

        verdict = self._check_repetition(calls, tool_name, args_hash)
        if verdict.action != LoopAction.ALLOW:
            return verdict

        verdict = self._check_ping_pong(calls)
        if verdict.action != LoopAction.ALLOW:
            return verdict

        verdict = self._check_no_progress_break(calls, tool_name)
        if verdict.action != LoopAction.ALLOW:
            return verdict

        verdict = self._check_divergence(calls)
        if verdict.action != LoopAction.ALLOW:
            return verdict

        verdict = self._check_consecutive_failures(calls)
        if verdict.action != LoopAction.ALLOW:
            return verdict

        tc = self._metrics.total_calls
        if tc == self._budget_warn:
            pct = tc * 100 // self._budget_stuck if self._budget_stuck else 70
            return LoopVerdict(
                action=LoopAction.WARN,
                reason=(
                    f"WARNING: You have used {pct}% of your iteration budget "
                    f"({tc} tool calls). Please review your original goal, "
                    f"re-evaluate your priorities, and focus on completing "
                    f"the most critical remaining tasks."
                ),
                backoff_hint="Review original goal and prioritize critical tasks. Avoid getting stuck in details.",
            )
        elif tc == self._budget_critical:
            pct = tc * 100 // self._budget_stuck if self._budget_stuck else 90
            return LoopVerdict(
                action=LoopAction.WARN,
                reason=(
                    f"CRITICAL WARNING: You have used {pct}% of your iteration "
                    f"budget ({tc} tool calls). You are about to run out of "
                    f"resources. You MUST finalize your work and provide a "
                    f"final answer immediately."
                ),
                backoff_hint="Finalize work immediately. Stop exploring.",
            )
        elif tc >= self._budget_stuck:
            from myrm_agent_harness.agent.errors.agent_errors import ToolStuckException

            self._record_detection(tool_name, LoopKind.CONSECUTIVE_FAILURES, tc)
            raise ToolStuckException(
                f"TOOL_STUCK_EXCEPTION: Iteration budget exhausted "
                f"({tc} tool calls). Provide your final answer now "
                f"with whatever results you have."
            )

        return self._check_output_diminishing()

    def record_result(self, tool_name: str, args: dict[str, object], result_text: str) -> LoopVerdict:
        """Record a completed tool call and check for no-progress loops."""
        if not self._window:
            return VERDICT_ALLOW

        rec = self._window[-1]
        rec.result_hash = _result_hash(tool_name, result_text)
        rec.result_content = result_text
        success_level = evaluate_success_level(tool_name, result_text)
        rec.success_level = success_level

        if self._pending_follow_check:
            self._metrics.effective_follows += success_level.weight
            if self._last_suggestion_key:
                self._metrics.update_suggestion_quality(self._last_suggestion_key, success_level)
                self._last_suggestion_key = None
        self._pending_follow_check = False

        if success_level == SuccessLevel.FAILURE:
            verdict = self._check_error_signature(tool_name, result_text)
            if verdict.action != LoopAction.ALLOW:
                return verdict

        return self._check_no_progress(list(self._window), tool_name)

    def tag_last_verification(self, vtype: VerificationCategory) -> None:
        """Mark the most recent CallRecord as a verification execution."""
        if self._window:
            self._window[-1].verification_type = vtype

    def get_metrics(self) -> LoopGuardMetrics:
        """Get current detection metrics."""
        return self._metrics

    @property
    def last_detection_kind(self) -> str | None:
        """Most recent loop pattern kind recorded in this session."""
        return self._last_detection_kind.value if self._last_detection_kind else None

    def reset_metrics(self) -> None:
        """Reset metrics counters."""
        self._metrics = LoopGuardMetrics()

    def reset(self, *, preserve_error_signatures: bool = False) -> None:
        """Clear all recorded calls and per-run state."""
        self._window.clear()
        self._last_warning_tool = None
        self._last_warning_args_hash = None
        self._pending_follow_check = False
        self._current_phase = AgentPhase.EXPLORATION
        self._last_suggestion_key = None
        self._last_detection_kind = None
        self._output_history.clear()
        self._last_recorded_call_index = -1
        if not preserve_error_signatures:
            self._error_signatures.clear()

    def notify_compaction(self) -> None:
        """Reset iteration-budget-sensitive state after context compaction.

        Context compaction discards older messages, effectively giving the
        agent a fresh working context.  The iteration budget counter
        (``total_calls``) must be reset so the agent is not prematurely
        terminated.  Error signatures are preserved so that recurring
        failures are still tracked across compaction boundaries.
        """
        self._window.clear()
        self._metrics.total_calls = 0
        self._output_history.clear()
        self._last_recorded_call_index = -1
        self._last_warning_tool = None
        self._last_warning_args_hash = None
        self._pending_follow_check = False
        self._last_suggestion_key = None
        self._last_detection_kind = None
