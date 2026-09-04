"""Wiki diagnostics — deterministic quality measurement.

[INPUT]
- .recall_benchmark::run_wiki_recall_benchmark (POS: offline retrieval benchmark)
- .structural_lint::collect_structural_lint_snapshot (POS: zero-LLM structural lint)

[OUTPUT]
- BENCHMARK_SCHEMA_VERSION, StructuralLintSnapshot, run_wiki_recall_benchmark, collect_structural_lint_snapshot

[POS]
Wiki diagnostics entry point. Re-exports deterministic linting and recall benchmark tooling.
"""

from myrm_agent_harness.toolkits.wiki.diagnostics.recall_benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    WikiRecallBenchmarkCase,
    WikiRecallBenchmarkResult,
    WikiRecallBenchmarkSummary,
    run_wiki_recall_benchmark,
    summarize_wiki_recall_benchmark,
)
from myrm_agent_harness.toolkits.wiki.diagnostics.structural_lint import (
    StructuralLintSnapshot,
    collect_broken_link_issues,
    collect_invalid_frontmatter_type_issues,
    collect_structural_lint_snapshot,
)

__all__ = [
    "BENCHMARK_SCHEMA_VERSION",
    "StructuralLintSnapshot",
    "WikiRecallBenchmarkCase",
    "WikiRecallBenchmarkResult",
    "WikiRecallBenchmarkSummary",
    "collect_broken_link_issues",
    "collect_invalid_frontmatter_type_issues",
    "collect_structural_lint_snapshot",
    "run_wiki_recall_benchmark",
    "summarize_wiki_recall_benchmark",
]
