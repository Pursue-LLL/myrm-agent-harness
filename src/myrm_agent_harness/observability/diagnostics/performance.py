"""[INPUT]
- protocols.py::HealthReport (POS: Component health status report.)

[OUTPUT]
- register_benchmark: Register an async performance benchmark hook function.
- run_all_benchmarks: Run all registered benchmark hooks concurrently and return reports.

[POS]
Provides register_benchmark, run_all_benchmarks for heavy performance testing.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .protocols import HealthReport

logger = logging.getLogger(__name__)

_benchmark_hooks: list[Callable[[], Awaitable[HealthReport]]] = []


def register_benchmark(func: Callable[[], Awaitable[HealthReport]]) -> None:
    """Register an async performance benchmark hook function."""
    if func not in _benchmark_hooks:
        _benchmark_hooks.append(func)


async def run_all_benchmarks() -> list[HealthReport]:
    """Run all registered benchmark hooks concurrently and return health reports."""
    if not _benchmark_hooks:
        return []

    async def _safe_execute_hook(hook: Callable[[], Awaitable[HealthReport]], timeout: float = 15.0) -> HealthReport:
        try:
            async with asyncio.timeout(timeout):
                return await hook()
        except TimeoutError:
            hook_name = getattr(hook, "__name__", "unknown_hook")
            return HealthReport(
                component_name=hook_name,
                status="fail",
                message="Benchmark timed out.",
                detail=f"Benchmark timed out (>{timeout}s).",
                fix_suggestion="Check network or API provider.",
            )
        except Exception as e:
            hook_name = getattr(hook, "__name__", "unknown_hook")
            return HealthReport(
                component_name=hook_name,
                status="fail",
                message="Benchmark encountered an unexpected error.",
                detail=f"Benchmark raised an uncaught exception: {e}",
                fix_suggestion="Check application logs for details.",
            )

    results = await asyncio.gather(*(_safe_execute_hook(hook) for hook in _benchmark_hooks), return_exceptions=True)

    reports: list[HealthReport] = []
    for idx, res in enumerate(results):
        if isinstance(res, HealthReport):
            reports.append(res)
        else:
            hook_name = getattr(_benchmark_hooks[idx], "__name__", f"hook_{idx}")
            reports.append(
                HealthReport(
                    component_name=hook_name,
                    status="fail",
                    message="An internal benchmark error occurred.",
                    detail=f"Unexpected return type {type(res)} or uncaught gather exception: {res}",
                    fix_suggestion="Check application logs for details.",
                )
            )

    return reports
