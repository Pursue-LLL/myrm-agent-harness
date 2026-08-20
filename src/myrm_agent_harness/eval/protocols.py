"""Eval Protocol — core types and AgentExecutor contract.

[INPUT]

[OUTPUT]
- EvalCase: test case definition
- MultiTurnEvalCase: multi-turn test case definition (with on_turn_fail strategy)
- OnTurnFail: type alias for multi-turn failure strategy
- EvalManifest: frozen environment snapshot for evaluation reproducibility
- EvalTurnResult: single-turn result
- EvalResult: aggregate result with reporting
-     AgentResponse: response from agent execution (with token_usage/cost tracking)
- AgentExecutor: protocol for business-layer implementation
- EvalTimings: performance timing data
- StateAssertion: output text assertion (supports contains/not_contains/regex/json_valid/json_schema/custom_python)
- SandboxAssertion: sandbox state assertion (file/cmd/json/test_suite with result_file + timeout + readonly_paths)
- SemanticAssertion: LLM-as-a-Judge assertion (supports custom judge_prompt/judge_model/threshold soft-scoring)
- RetrievalAssertion: RAG & Memory retrieval quality assertion (Head/Tail spans, collapse hits, duplicate rate)

[POS]
Defines the eval framework's type system and the AgentExecutor protocol.
Framework has zero business-layer dependency — all agent interaction
flows through the AgentExecutor protocol injected by the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor


@dataclass(frozen=True, slots=True)
class SandboxAssertion:
    """Sandbox state assertion definition."""

    type: str  # e.g., "file_exists", "file_contains", "cmd_success", "test_suite"
    target: str  # e.g., file path or command
    expected: str | None = None  # e.g., expected text content
    result_file: str | None = None  # e.g., test_suite: path to JUnit/reward result file
    timeout: int | None = None  # e.g., test_suite: command timeout in seconds (default 600)
    readonly_paths: tuple[
        str, ...
    ] = ()  # e.g., test_suite: read-only grader assets mounted outside the agent workspace


@dataclass(frozen=True, slots=True)
class StateAssertion:
    """Agent state or output mutation assertion definition."""

    type: str  # e.g., "exact_match", "contains", "jaccard_similarity"
    expected: str
    threshold: float = 0.8  # Used for similarity checks


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    """Caller-level judge LLM credentials resolved by the eval runner.

    Injected into semantic assertions so the LLM judge reuses the caller's
    model configuration (provider API key/base URL) instead of requiring
    ambient provider environment variables.
    """

    model: str
    api_key: str | None = None
    api_base: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticAssertion:
    """LLM-as-a-Judge semantic assertion definition."""

    type: str  # e.g., "llm_judge"
    expected: str  # The criteria or prompt to judge against
    threshold: float = 1.0  # Optional threshold for soft scoring (e.g. 0-1)
    judge_prompt: str | None = None  # Custom system prompt for the judge LLM
    judge_model: str | None = None  # Override judge model (e.g., "gpt-3.5-turbo")
    judge_api_key: str | None = None  # Override judge API key (litellm-compatible)
    judge_api_base: str | None = None  # Override judge base URL (litellm-compatible)


@dataclass(frozen=True, slots=True)
class RetrievalAssertion:
    """RAG & Memory retrieval quality assertion.

    Supports:
    - min_recall: Minimum required recall rate (0.0~1.0)
    - expected_spans: Verbatim body text quotes that must appear in body hits (after header stripping)
    - expected_doc_ids: Required document / memory IDs in top-k
    - max_duplicate_rate: Maximum allowed duplicate chunk rate from the same document (0.0~1.0)
    - min_distinct_sources: Minimum distinct documents / files in top-k
    - top_k: Top-K evaluation window (default 5)
    - strip_headers: Whether to strip markdown/yaml headers before matching spans
    """

    type: str = "retrieval_quality"
    expected_spans: tuple[str, ...] = ()
    expected_doc_ids: tuple[str, ...] = ()
    min_recall: float = 1.0
    max_duplicate_rate: float | None = None
    min_distinct_sources: int | None = None
    top_k: int = 5
    strip_headers: bool = True


@dataclass(frozen=True, slots=True)
class EvalCase:
    """Single eval test case."""

    message: str
    expected_tools: list[str | dict[str, Any]] = field(default_factory=list)
    require_all: bool = False
    sandbox_assertions: list[SandboxAssertion] = field(default_factory=list)
    state_assertions: list[StateAssertion] = field(default_factory=list)
    semantic_assertions: list[SemanticAssertion] = field(default_factory=list)
    retrieval_assertions: list[RetrievalAssertion] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


OnTurnFail = Literal["continue", "skip_remaining", "abort"]


@dataclass(frozen=True, slots=True)
class MultiTurnEvalCase:
    """Multi-turn eval test case — ordered sequence of turns."""

    turns: list[EvalCase]
    on_turn_fail: OnTurnFail = "continue"
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class EvalTimings:
    """Performance timing data for a single eval turn (milliseconds)."""

    total_ms: float = 0.0
    extra: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResponse:
    """Response from agent execution — returned by AgentExecutor."""

    answer: str
    tools_called: list[str | dict[str, Any]] = field(default_factory=list)
    tool_call_details: list[dict[str, object]] = field(default_factory=list)
    retrieved_hits: list[dict[str, object]] = field(default_factory=list)
    extra_timings: dict[str, float] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    # ``limit_type`` (e.g. "max_tool_calls") when the engine stopped the run
    # because a configured budget was exhausted — disclosed so a report never
    # mistakes a truncated run for a complete answer.
    limit_reached: str | None = None
    # Number of tool invocations rejected by a benchmark decontamination
    # blocklist (blocked host / blocked query). Lets a report disclose that
    # pollution guards actually engaged during the run.
    blocked_count: int = 0


@dataclass(slots=True)
class EvalTurnResult:
    """Result of a single eval turn."""

    case: EvalCase
    response: AgentResponse
    assertion_passed: bool | None = None
    assertion_details: str | None = None
    timings: EvalTimings = field(default_factory=EvalTimings)
    error: str | None = None
    scores: dict[str, float] = field(default_factory=dict)  # numeric verdicts (e.g. test_suite pass_rate)


@dataclass(frozen=True, slots=True)
class EvalManifest:
    """Environment snapshot for evaluation reproducibility.

    Captures all dimensions that affect eval outcomes so that two runs
    can be compared meaningfully. Generated by the business layer and
    embedded into the evaluation report by the reporter.
    """

    model_provider: str
    model_id: str
    harness_version: str
    tool_policy: tuple[str, ...]
    task_set_id: str
    task_set_hash: str
    prompt_fingerprint: str
    budget_max_tokens: int
    timeout_seconds: int
    created_at: str
    thinking_effort: str = "default"
    profile_id: str = "default"
    benchmark_mode: bool = False
    judge_model: str = "none"  # LLM judge model used for semantic assertions
    limit: int | None = None  # Reproducible sample size actually applied (None = full run)
    max_tool_calls: int | None = None  # Benchmark-declared tool-call budget (None = engine default)
    max_iterations: int | None = None  # Benchmark-declared turn budget (None = engine default)

    def to_dict(self) -> dict[str, object]:
        return {
            "model_provider": self.model_provider,
            "model_id": self.model_id,
            "thinking_effort": self.thinking_effort,
            "harness_version": self.harness_version,
            "tool_policy": list(self.tool_policy),
            "task_set_id": self.task_set_id,
            "task_set_hash": self.task_set_hash,
            "prompt_fingerprint": self.prompt_fingerprint,
            "budget_max_tokens": self.budget_max_tokens,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
            "profile_id": self.profile_id,
            "benchmark_mode": self.benchmark_mode,
            "judge_model": self.judge_model,
            "limit": self.limit,
            "max_tool_calls": self.max_tool_calls,
            "max_iterations": self.max_iterations,
        }


@dataclass(slots=True)
class EvalResult:
    """Aggregate eval result with reporting utilities."""

    turn_results: list[EvalTurnResult] = field(default_factory=list)
    total_ms: float = 0.0
    manifest: EvalManifest | None = None

    @property
    def total_cases(self) -> int:
        return len(self.turn_results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.turn_results if r.assertion_passed is True)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.turn_results if r.assertion_passed is False)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.turn_results if r.error is not None)

    @property
    def skip_count(self) -> int:
        """Cases with no assertions (assertion_passed is None and no error)."""
        return sum(1 for r in self.turn_results if r.assertion_passed is None and r.error is None)

    @property
    def pass_rate(self) -> float:
        asserted = self.pass_count + self.fail_count
        return self.pass_count / asserted if asserted > 0 else 0.0

    @property
    def avg_pass_rate(self) -> float | None:
        """Mean of per-turn test pass_rates (None when no turn reports scores).

        Unlike ``pass_rate`` (binary case-level pass/fail), this aggregates the
        numeric Rule-judge pass_rates so partial successes (e.g. 62/80 tests)
        are not flattened away at the report level.
        """
        rates = [r.scores["pass_rate"] for r in self.turn_results if r.scores.get("pass_rate") is not None]
        if not rates:
            return None
        return round(sum(rates) / len(rates), 4)

    @property
    def all_passed(self) -> bool:
        return self.fail_count == 0 and self.error_count == 0

    @property
    def total_tokens(self) -> int:
        """Sum of total_tokens across all turns."""
        return sum(r.response.token_usage.get("total_tokens", 0) for r in self.turn_results)

    @property
    def total_cost(self) -> float:
        """Sum of cost across all turns."""
        return sum(r.response.cost for r in self.turn_results)

    def to_dict(self) -> dict[str, object]:
        """Export as JSON-serializable dict for business-layer consumption."""
        result: dict[str, object] = {
            "total_cases": self.total_cases,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "error_count": self.error_count,
            "skip_count": self.skip_count,
            "pass_rate": round(self.pass_rate, 4),
            "all_passed": self.all_passed,
            "total_ms": round(self.total_ms, 2),
            "total_tokens": self.total_tokens,
            "total_cost": round(self.total_cost, 6),
        }
        if self.avg_pass_rate is not None:
            result["avg_pass_rate"] = self.avg_pass_rate
        if self.manifest is not None:
            result["manifest"] = self.manifest.to_dict()
        result["turns"] = [
            {
                "message": r.case.message,
                "expected_tools": r.case.expected_tools,
                "sandbox_assertions": [
                    {
                        "type": a.type,
                        "target": a.target,
                        "expected": a.expected,
                        "result_file": a.result_file,
                        "timeout": a.timeout,
                        "readonly_paths": list(a.readonly_paths),
                    }
                    for a in r.case.sandbox_assertions
                ],
                "state_assertions": [
                    {"type": a.type, "expected": a.expected, "threshold": a.threshold} for a in r.case.state_assertions
                ],
                "semantic_assertions": [
                    {
                        "type": a.type,
                        "expected": a.expected,
                        "threshold": a.threshold,
                        **({"judge_prompt": a.judge_prompt} if a.judge_prompt else {}),
                        **({"judge_model": a.judge_model} if a.judge_model else {}),
                        **({"judge_api_key": a.judge_api_key} if a.judge_api_key else {}),
                        **({"judge_api_base": a.judge_api_base} if a.judge_api_base else {}),
                    }
                    for a in r.case.semantic_assertions
                ],
                "retrieval_assertions": [
                    {
                        "type": a.type,
                        "expected_spans": list(a.expected_spans),
                        "expected_doc_ids": list(a.expected_doc_ids),
                        "min_recall": a.min_recall,
                        "max_duplicate_rate": a.max_duplicate_rate,
                        "min_distinct_sources": a.min_distinct_sources,
                        "top_k": a.top_k,
                        "strip_headers": a.strip_headers,
                    }
                    for a in r.case.retrieval_assertions
                ],
                "tools_called": r.response.tools_called,
                "tool_call_details": r.response.tool_call_details,
                "retrieved_hits": r.response.retrieved_hits,
                "limit_reached": r.response.limit_reached,
                "blocked_count": r.response.blocked_count,
                "assertion_passed": r.assertion_passed,
                "assertion_details": r.assertion_details,
                "scores": r.scores,
                "total_ms": round(r.timings.total_ms, 2),
                "token_usage": r.response.token_usage,
                "cost": r.response.cost,
                "error": r.error,
            }
            for r in self.turn_results
        ]
        return result

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        return (
            f"Eval: {self.pass_count}/{self.total_cases} passed "
            f"({self.pass_rate:.0%}), "
            f"{self.fail_count} failed, {self.error_count} errors, "
            f"{self.total_ms:.0f}ms"
        )


@runtime_checkable
class AgentExecutor(Protocol):
    """Protocol for business-layer agent execution.

    Framework does not know how to create agents, connect to databases,
    or handle isolation. Business layer implements this protocol to bridge
    eval framework with the actual agent system.
    """

    async def execute(self, message: str, *, session_id: str | None = None) -> AgentResponse:
        """Send a message to the agent and collect the response.

        For multi-turn evals, the same session_id is passed across turns
        to maintain conversation context.
        """
        ...

    async def create_session(self) -> str:
        """Create an isolated eval session and return its ID.

        Business layer controls isolation strategy (e.g. DB savepoint rollback,
        ephemeral containers, or in-memory sessions).
        """
        ...

    def get_sandbox_executor(self, session_id: str | None = None) -> CodeExecutor | None:
        """Return the SandboxExecutor for this session if available.

        Used for evaluating sandbox state assertions (e.g., file_exists).
        """
        return None
