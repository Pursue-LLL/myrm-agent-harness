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
    calculate_trajectory_determinism,
    collapse_retrieval_hits,
    evaluate_post_episode_assertions,
    evaluate_retrieval_assertions,
    evaluate_sandbox_assertions,
    evaluate_semantic_assertions,
    evaluate_state_assertions,
    evaluate_tool_assertions,
)
from .benchmarks import (
    BenchmarkSpec,
    get_benchmark,
    list_benchmarks,
    register_benchmark,
)
from .builder import build_skill_eval_cases, extract_case_from_trajectory
from .canary import (
    CANARY_GUID,
    CANARY_PREAMBLE,
    CanaryScanResult,
    EvalCanaryGate,
    embed_canary_header,
    scan_dataset_canary_integrity,
    verify_canary_presence,
)
from .compaction_ab import CompactionABEvaluator, CompactionABResult
from .compaction_assertions import (
    canonicalize_tool_name,
    evaluate_compaction_assertions,
)
from .contamination import (
    DEFAULT_HIDDEN_TEST_PATTERNS,
    ContaminationAuditResult,
    ContaminationViolation,
    ContaminationViolationType,
    audit_episode_trajectory_for_contamination,
    scrub_canary_from_query,
    verify_workspace_clean_of_hidden_tests,
)
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
    DeterminismReplayResult,
    EvalCase,
    EvalManifest,
    EvalResult,
    EvalTimings,
    EvalTurnResult,
    JudgeConfig,
    MultiTurnEvalCase,
    OnTurnFail,
    OperationalAssuranceCategory,
    PostEpisodeAssertion,
    RetrievalAssertion,
    SandboxAssertion,
    SemanticAssertion,
    SkillABArmMetrics,
    SkillABReportData,
    StateAssertion,
)
from .reporters import JsonlReporter, MarkdownReporter
from .runner import EvalRunner
from .trajectory_analysis import (
    WEIGHTS_RUBRIC_7D,
    FailureMode,
    TrajectoryFailureAnalysis,
    aggregate_failure_modes,
    analyze_turn_failure_mode,
)

__all__ = [
    "CANARY_GUID",
    "CANARY_PREAMBLE",
    "DEFAULT_HIDDEN_TEST_PATTERNS",
    "FailureMode",
    "HUGGINGFACE_DOMAINS",
    "HUGGINGFACE_QUERY_MARKERS",
    "TrajectoryFailureAnalysis",
    "WEIGHTS_RUBRIC_7D",
    "AgentExecutor",
    "AgentResponse",
    "BenchmarkSpec",
    "CanaryScanResult",
    "CollapsedHit",
    "CompactionABEvaluator",
    "CompactionABResult",
    "CompactionAssertion",
    "CompactionFidelityScore",
    "ContaminationAuditResult",
    "ContaminationViolation",
    "ContaminationViolationType",
    "DeterminismReplayResult",
    "EvalCanaryGate",
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
    "PostEpisodeAssertion",
    "RetrievalAssertion",
    "SandboxAssertion",
    "SemanticAssertion",
    "SkillABArmMetrics",
    "SkillABReportData",
    "StateAssertion",
    "ToolAssertion",
    "aggregate_failure_modes",
    "analyze_turn_failure_mode",
    "audit_episode_trajectory_for_contamination",
    "build_skill_eval_cases",
    "calculate_trajectory_determinism",
    "canonicalize_tool_name",
    "collapse_retrieval_hits",
    "embed_canary_header",
    "evaluate_compaction_assertions",
    "evaluate_post_episode_assertions",
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
    "scan_dataset_canary_integrity",
    "scrub_canary_from_query",
    "verify_canary_presence",
    "verify_workspace_clean_of_hidden_tests",
]
