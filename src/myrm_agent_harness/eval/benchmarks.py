"""Third-party benchmark catalog — generic spec + registry.

[INPUT]
- none (pure framework types)

[OUTPUT]
- BenchmarkSpec: immutable descriptor for an external benchmark dataset
- register_benchmark / list_benchmarks / get_benchmark: process-wide registry

[POS]
Framework-generic mechanism for admitting third-party benchmarks into the
Eval Lab (SWE-bench, BrowseComp, Terminal-Bench, ...). The spec only carries
metadata a fair run needs; concrete dataset download/parse/grading adapters
live in the business layer and register their spec here so the frontend and
the eval service can discover them uniformly. No concrete benchmark data is
baked into the framework.
"""

from __future__ import annotations

from dataclasses import dataclass

RegistryT = dict[str, "BenchmarkSpec"]

_registry: RegistryT = {}


@dataclass(frozen=True, slots=True)
class BenchmarkSpec:
    """Immutable descriptor for one third-party benchmark dataset.

    Attributes:
        id: Stable machine id (e.g. ``browsecomp``). Used as the dataset id
            and by the API/registry.
        display_name: Human-readable name for the UI.
        description: One-line purpose statement shown in the benchmark cards.
        download_url: Where the raw dataset archive lives (best-effort; the
            business adapter owns download/verify/extract).
        task_count: Number of tasks in the official test set (0 = unknown).
        approx_size_mb: Approximate download size for the UI (0 = unknown).
        scoring: Grading strategy label (``llm_judge`` / ``native`` /
            ``composite``). Drives the badge shown on the benchmark card.
        required_tools: Builtin-tool ids the benchmark needs to be runnable in
            ``benchmark_mode`` (e.g. ``("web_search",)`` for BrowseComp). The
            executor injects exactly this whitelist on top of the CORE file /
            shell mount, keeping the baseline otherwise user-config-free.
        supports_memory_ab: Whether the dataset is suitable for the Memory A/B
            comparison flow (``False`` hides the Memory A/B button).
        max_tool_calls: Per-run tool-call budget the executor must apply in
            ``benchmark_mode`` (0 = inherit the engine default of 30). Large
            multi-hop suites (e.g. BrowseComp web research) declare a higher
            ceiling so the scored run measures the model, not the limit.
        max_iterations: Per-run LangGraph recursion budget (0 = inherit the
            engine default of 50). Mirrors ``max_tool_calls``; both ceilings
            must be lifted together for long-horizon suites.
        harness: Which harness the official run is graded against —
            ``"myrm"`` (our eval runtime) or ``"official"`` (the publisher's
            own harness). Kept in the spec so an ``"official"`` reference
            score stays distinguishable from our harness's measurement.
        judge_prompt: Default LLM-judge grading prompt for the benchmark.
            Registered centrally so the eval service can surface/disclose it
            and adapters stay consistent (the concrete per-case assertion may
            still override via ``SemanticAssertion.judge_prompt``).
    """

    id: str
    display_name: str
    description: str
    download_url: str = ""
    task_count: int = 0
    approx_size_mb: int = 0
    scoring: str = "llm_judge"
    required_tools: tuple[str, ...] = ()
    supports_memory_ab: bool = True
    max_tool_calls: int = 0
    max_iterations: int = 0
    harness: str = "myrm"
    judge_prompt: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.display_name,
            "description": self.description,
            "task_count": self.task_count,
            "approx_size_mb": self.approx_size_mb,
            "scoring": self.scoring,
            "required_tools": list(self.required_tools),
            "supports_memory_ab": self.supports_memory_ab,
            "max_tool_calls": self.max_tool_calls,
            "max_iterations": self.max_iterations,
            "harness": self.harness,
            "judge_prompt": self.judge_prompt,
        }


def register_benchmark(spec: BenchmarkSpec) -> None:
    """Register a benchmark spec (idempotent; last registration wins).

    Called by business-layer adapters at import time so the catalog is fully
    populated before the eval API serves list requests.
    """
    _registry[spec.id] = spec


def list_benchmarks() -> tuple[BenchmarkSpec, ...]:
    """Return all registered benchmarks in registration order."""
    return tuple(_registry.values())


def get_benchmark(benchmark_id: str) -> BenchmarkSpec | None:
    """Return a registered spec, or None when unknown."""
    return _registry.get(benchmark_id)


__all__ = [
    "BenchmarkSpec",
    "get_benchmark",
    "list_benchmarks",
    "register_benchmark",
]
