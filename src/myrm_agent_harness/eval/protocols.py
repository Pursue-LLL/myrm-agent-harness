"""Eval Protocol — core types and AgentExecutor contract.

[INPUT]

[OUTPUT]
- EvalCase: test case definition
- MultiTurnEvalCase: multi-turn test case definition
- EvalTurnResult: single-turn result
- EvalResult: aggregate result with reporting
- AgentResponse: response from agent execution (with token_usage/cost tracking)
- AgentExecutor: protocol for business-layer implementation
- EvalTimings: performance timing data
- StateAssertion: output text assertion (supports contains/not_contains/regex/json_valid/json_schema/custom_python)
- SandboxAssertion: sandbox state assertion
- SemanticAssertion: LLM-as-a-Judge assertion (supports custom judge_prompt/judge_model/threshold soft-scoring)

[POS]
Defines the eval framework's type system and the AgentExecutor protocol.
Framework has zero business-layer dependency — all agent interaction
flows through the AgentExecutor protocol injected by the caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor


@dataclass(frozen=True, slots=True)
class SandboxAssertion:
    """Sandbox state assertion definition."""

    type: str  # e.g., "file_exists", "file_contains", "cmd_success"
    target: str  # e.g., file path or command
    expected: str | None = None  # e.g., expected text content


@dataclass(frozen=True, slots=True)
class StateAssertion:
    """Agent state or output mutation assertion definition."""

    type: str  # e.g., "exact_match", "contains", "jaccard_similarity"
    expected: str
    threshold: float = 0.8  # Used for similarity checks


@dataclass(frozen=True, slots=True)
class SemanticAssertion:
    """LLM-as-a-Judge semantic assertion definition."""

    type: str  # e.g., "llm_judge"
    expected: str  # The criteria or prompt to judge against
    threshold: float = 1.0  # Optional threshold for soft scoring (e.g. 0-1)
    judge_prompt: str | None = None  # Custom system prompt for the judge LLM
    judge_model: str | None = None  # Override judge model (e.g., "gpt-3.5-turbo")


@dataclass(frozen=True, slots=True)
class EvalCase:
    """Single eval test case."""

    message: str
    expected_tools: list[str | dict[str, Any]] = field(default_factory=list)
    require_all: bool = False
    sandbox_assertions: list[SandboxAssertion] = field(default_factory=list)
    state_assertions: list[StateAssertion] = field(default_factory=list)
    semantic_assertions: list[SemanticAssertion] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MultiTurnEvalCase:
    """Multi-turn eval test case — ordered sequence of turns."""

    turns: list[EvalCase]
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
    extra_timings: dict[str, float] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0


@dataclass(slots=True)
class EvalTurnResult:
    """Result of a single eval turn."""

    case: EvalCase
    response: AgentResponse
    assertion_passed: bool | None = None
    assertion_details: str | None = None
    timings: EvalTimings = field(default_factory=EvalTimings)
    error: str | None = None


@dataclass(slots=True)
class EvalResult:
    """Aggregate eval result with reporting utilities."""

    turn_results: list[EvalTurnResult] = field(default_factory=list)
    total_ms: float = 0.0

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
    def all_passed(self) -> bool:
        return self.fail_count == 0 and self.error_count == 0

    def to_dict(self) -> dict[str, object]:
        """Export as JSON-serializable dict for business-layer consumption."""
        return {
            "total_cases": self.total_cases,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "error_count": self.error_count,
            "skip_count": self.skip_count,
            "pass_rate": round(self.pass_rate, 4),
            "all_passed": self.all_passed,
            "total_ms": round(self.total_ms, 2),
            "turns": [
                {
                    "message": r.case.message,
                    "expected_tools": r.case.expected_tools,
                    "sandbox_assertions": [
                        {"type": a.type, "target": a.target, "expected": a.expected} for a in r.case.sandbox_assertions
                    ],
                    "state_assertions": [
                        {"type": a.type, "expected": a.expected, "threshold": a.threshold}
                        for a in r.case.state_assertions
                    ],
                    "semantic_assertions": [
                        {"type": a.type, "expected": a.expected, "threshold": a.threshold}
                        for a in r.case.semantic_assertions
                    ],
                    "tools_called": r.response.tools_called,
                    "assertion_passed": r.assertion_passed,
                    "assertion_details": r.assertion_details,
                    "total_ms": round(r.timings.total_ms, 2),
                    "error": r.error,
                }
                for r in self.turn_results
            ],
        }

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
