"""Eval Framework — Agent behavior quality evaluation.

Public API:
- Types: EvalCase, MultiTurnEvalCase, OnTurnFail, EvalResult, EvalTurnResult, AgentResponse, EvalTimings
- Protocol: AgentExecutor
- Assertions: ToolAssertion, evaluate_tool_assertions
- Runner: EvalRunner
- Matrix: MatrixRunner, MatrixResult, MatrixCellResult
- Loader: load_cases, load_multi_turn_cases
"""

from .assertions import (
    CollapsedHit,
    ToolAssertion,
    canonicalize_tool_name,
    collapse_retrieval_hits,
    evaluate_compaction_assertions,
    evaluate_retrieval_assertions,
    evaluate_sandbox_assertions,
    evaluate_semantic_assertions,
    evaluate_state_assertions,
    evaluate_tool_assertions,
)
from .benchmarks import BenchmarkSpec, get_benchmark, list_benchmarks, register_benchmark
from .builder import build_skill_eval_cases, extract_case_from_trajectory
from .compaction_ab import CompactionABEvaluator, CompactionABResult
from .compaction_assertions import evaluate_compaction_assertions
from .decontam import (
    HUGGINGFACE_DOMAINS,
    HUGGINGFACE_QUERY_MARKERS,
    normalize_answer,
)
from .loader import load_cases, load_multi_turn_cases
from .matrix import MatrixCellResult, MatrixResult, MatrixRunner
from .protocols import (
    AgentExecutor,
    AgentResponse,
    CompactionAssertion,
    CompactionFidelityScore,
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    JudgeConfig,
    MultiTurnEvalCase,
    OnTurnFail,
    OperationalAssuranceCategory,
    RetrievalAssertion,
    SandboxAssertion,
    SemanticAssertion,
    StateAssertion,
)
from .reporters import JsonlReporter, MarkdownReporter
from .runner import EvalRunner

__all__ = [
    "HUGGINGFACE_DOMAINS",
    "HUGGINGFACE_QUERY_MARKERS",
    "AgentExecutor",
    "AgentResponse",
    "BenchmarkSpec",
    "CollapsedHit",
    "CompactionABEvaluator",
    "CompactionABResult",
    "CompactionAssertion",
    "CompactionFidelityScore",
    "EvalCase",
    "EvalManifest",
    "EvalResult",
    "EvalRunner",
    "EvalTimings",
    "EvalTurnResult",
    "JsonlReporter",
    "JudgeConfig",
    "MarkdownReporter",
    "MatrixCellResult",
    "MatrixResult",
    "MatrixRunner",
    "MultiTurnEvalCase",
    "OnTurnFail",
    "OperationalAssuranceCategory",
    "RetrievalAssertion",
    "SandboxAssertion",
    "SemanticAssertion",
    "StateAssertion",
    "ToolAssertion",
    "build_skill_eval_cases",
    "collapse_retrieval_hits",
    "evaluate_retrieval_assertions",
    "evaluate_sandbox_assertions",
    "evaluate_semantic_assertions",
    "evaluate_state_assertions",
    "evaluate_tool_assertions",
    "extract_case_from_trajectory",
    "get_benchmark",
    "list_benchmarks",
    "load_cases",
    "load_multi_turn_cases",
    "normalize_answer",
    "register_benchmark",
]
