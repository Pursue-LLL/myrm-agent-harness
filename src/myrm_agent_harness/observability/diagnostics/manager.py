"""[INPUT]
- (none)

[OUTPUT]
- register_diagnostic: Register an async health-check hook function.
- register_protocol: Register a class instance that implements ``DiagnosticPro...
- run_all_diagnostics: Run all registered diagnostic hooks concurrently and retu...

[POS]
Provides register_diagnostic, register_protocol, run_all_diagnostics.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from .protocols import DiagnosticProtocol, HealthReport

logger = logging.getLogger(__name__)

_diagnostic_hooks: list[Callable[[], Awaitable[HealthReport]]] = []


def register_diagnostic(func: Callable[[], Awaitable[HealthReport]]) -> None:
    """Register an async health-check hook function."""
    if func not in _diagnostic_hooks:
        _diagnostic_hooks.append(func)


def register_protocol(instance: DiagnosticProtocol) -> None:
    """Register a class instance that implements ``DiagnosticProtocol``."""
    if isinstance(instance, DiagnosticProtocol):
        register_diagnostic(instance.check_health)
    else:
        logger.warning("Cannot register diagnostic protocol: %r does not implement DiagnosticProtocol", instance)


async def run_all_diagnostics() -> list[HealthReport]:
    """Run all registered diagnostic hooks concurrently and return health reports."""
    if not _diagnostic_hooks:
        return []

    async def _safe_execute_hook(hook: Callable[[], Awaitable[HealthReport]], timeout: float = 5.0) -> HealthReport:
        try:
            async with asyncio.timeout(timeout):
                return await hook()
        except TimeoutError:
            hook_name = getattr(hook, "__name__", "unknown_hook")
            return HealthReport(
                component_name=hook_name,
                status="fail",
                message="A system component is not responding.",
                detail=f"Diagnostic timed out (>{timeout}s), component may be deadlocked.",
                fix_suggestion="Try restarting the application.",
            )
        except Exception as e:
            hook_name = getattr(hook, "__name__", "unknown_hook")
            return HealthReport(
                component_name=hook_name,
                status="fail",
                message="A system check encountered an unexpected error.",
                detail=f"Diagnostic raised an uncaught exception: {e}",
                fix_suggestion="Check application logs for details.",
            )

    results = await asyncio.gather(*(_safe_execute_hook(hook) for hook in _diagnostic_hooks), return_exceptions=True)

    reports: list[HealthReport] = []
    for idx, res in enumerate(results):
        if isinstance(res, HealthReport):
            reports.append(res)
        else:
            hook_name = getattr(_diagnostic_hooks[idx], "__name__", f"hook_{idx}")
            reports.append(
                HealthReport(
                    component_name=hook_name,
                    status="fail",
                    message="An internal diagnostics error occurred.",
                    detail=f"Unexpected return type {type(res)} or uncaught gather exception: {res}",
                    fix_suggestion="Check application logs for details.",
                )
            )

    return reports
