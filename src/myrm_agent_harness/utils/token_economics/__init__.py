"""LLM call economics subsystem — token tracking, cost calculation, cache economics, audit logs, budget control.

[POS]
LLM call full-chain economic metrics: token usage tracking (7 token types), cost calculation, and budget management.

"""

from importlib import import_module as _import_module

_EXPORTS: dict[str, tuple[str, str]] = {
    # tracker.py
    "TokenUsage": (".tracker", "TokenUsage"),
    "LatencyStats": (".tracker", "LatencyStats"),
    "TokenTracker": (".tracker", "TokenTracker"),
    "init_token_tracker": (".tracker", "init_token_tracker"),
    "get_token_tracker": (".tracker", "get_token_tracker"),
    "reset_token_tracker": (".tracker", "reset_token_tracker"),
    "record_token_usage": (".tracker", "record_token_usage"),
    "push_tool_context": (".tracker", "push_tool_context"),
    "pop_tool_context": (".tracker", "pop_tool_context"),
    "record_token_error": (".tracker", "record_token_error"),
    "record_finish_reason": (".tracker", "record_finish_reason"),
    "get_pending_token_events": (".tracker", "get_pending_token_events"),
    "append_to_ledger": (".tracker", "append_to_ledger"),
    "set_usage_ledger": (".tracker", "set_usage_ledger"),
    "setup_token_tracking_callback": (".tracker", "setup_token_tracking_callback"),
    # cost_engine.py
    "CostStatus": (".cost_engine", "CostStatus"),
    "CostResult": (".cost_engine", "CostResult"),
    "compute_cost": (".cost_engine", "compute_cost"),
    "compute_cost_by_tokens": (".cost_engine", "compute_cost_by_tokens"),
    # cache_economics.py
    "compute_prompt_cache_stats": (".cache_economics", "compute_prompt_cache_stats"),
    "coerce_usage_non_negative_int": (".cache_economics", "coerce_usage_non_negative_int"),
    # usage_ledger.py
    "UsageRecord": (".usage_ledger", "UsageRecord"),
    "UsageLedger": (".usage_ledger", "UsageLedger"),
    # budget_guard.py
    "BudgetStatus": (".budget_guard", "BudgetStatus"),
    "BudgetChecker": (".budget_guard", "BudgetChecker"),
    "DailyBudgetGuard": (".budget_guard", "DailyBudgetGuard"),
    # multidim_budget.py
    "BudgetDimension": (".multidim_budget", "BudgetDimension"),
    "MultidimensionalBudgetGuard": (".multidim_budget", "MultidimensionalBudgetGuard"),
    # budget_boundary_middleware.py
    "BudgetBoundaryMiddleware": (".budget_boundary_middleware", "BudgetBoundaryMiddleware"),
}

__all__ = list(_EXPORTS.keys())


def __getattr__(name: str) -> object:
    try:
        module_path, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = _import_module(module_path, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(__all__ + [name for name in globals() if not name.startswith("_")]))
