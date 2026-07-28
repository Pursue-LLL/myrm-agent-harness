"""Eval Framework — Agent behavior quality evaluation.

Public API:
- Types: EvalCase, MultiTurnEvalCase, EvalResult, EvalTurnResult, AgentResponse, EvalTimings
- Protocol: AgentExecutor
- Assertions: ToolAssertion, evaluate_tool_assertions
- Runner: EvalRunner
- Loader: load_cases, load_multi_turn_cases
"""

from .assertions import (
    ToolAssertion,
    evaluate_sandbox_assertions,
    evaluate_state_assertions,
    evaluate_tool_assertions,
)
from .builder import build_skill_eval_cases, extract_case_from_trajectory
from .loader import load_cases, load_multi_turn_cases
from .protocols import (
    AgentExecutor,
    AgentResponse,
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    MultiTurnEvalCase,
    SandboxAssertion,
    StateAssertion,
)
from .reporters import JsonlReporter, MarkdownReporter
from .runner import EvalRunner

__all__ = [
    "AgentExecutor",
    "AgentResponse",
    "EvalCase",
    "EvalManifest",
    "EvalResult",
    "EvalRunner",
    "EvalTimings",
    "EvalTurnResult",
    "JsonlReporter",
    "MarkdownReporter",
    "MultiTurnEvalCase",
    "SandboxAssertion",
    "StateAssertion",
    "ToolAssertion",
    "build_skill_eval_cases",
    "evaluate_sandbox_assertions",
    "evaluate_state_assertions",
    "evaluate_tool_assertions",
    "extract_case_from_trajectory",
    "load_cases",
    "load_multi_turn_cases",
]
