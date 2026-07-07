# token_economics/

## Overview
LLM call full-chain economic metrics: token usage tracking (7 token types), cost calculation, budget management, and multi-dimensional budget enforcement with mid-conversation finalization.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | LLM call full-chain economic metrics: token usage tracking (7 token types), cost calculation, and budget management. | — |
| budget_guard.py | Core | Budget guard protocol + simple daily implementation. Defines BudgetChecker protocol and BudgetStatus enum. | ✅ |
| multidim_budget.py | Core | Multi-dimensional budget guard. Supports per-session, daily, and per-call limits with three-level progressive response. | ✅ |
| budget_boundary_middleware.py | Core | AgentMiddleware that enforces budget limits mid-conversation via prompt injection and tool-call stripping. | ✅ |
| cache_economics.py | Core | Framework-neutral utilities under ``utils/``; safe for any layer to import. | ✅ |
| cache_savings.py | Core | Provides calculate_cache_savings_usd. | ✅ |
| cost_engine.py | Core | Thin wrapper over litellm.completion_cost() that adds CostStatus provenance. | ✅ |
| tracker.py | Core | LLM call metadata tracker. ContextVar-based request-level tracking supporting both streaming and non-streaming calls. | ✅ |
| usage_ledger.py | Core | Lightweight audit log recording token count, cost, latency, and model metadata for each LLM call. | ✅ |

## Budget Control Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Frontend: BudgetPolicySection (settings UI + progress bar)     │
│  + SSE toast notifications (warning / finalization / exceeded)  │
└───────────────┬─────────────────────────────────────────────────┘
                │ PUT /budget/policy  GET /budget/status
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Server: enforcer.py                                            │
│  BudgetPolicy (Pydantic) → MultidimensionalBudgetGuard singleton│
│  + SSE callbacks → EventBus → Frontend                          │
│  + reset_session_budget() called per new conversation           │
└───────────────┬─────────────────────────────────────────────────┘
                │ BudgetChecker protocol
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Harness: MultidimensionalBudgetGuard                           │
│  3 dimensions: per-session / daily / per-call                   │
│  3 levels: OK → WARNING → FINALIZATION → EXCEEDED               │
│  Thread-safe, auto day-reset                                    │
└───────────────┬─────────────────────────────────────────────────┘
                │ TokenTracker.record() → BudgetChecker.record_cost()
                ▼
┌─────────────────────────────────────────────────────────────────┐
│  Harness: BudgetBoundaryMiddleware (in agent loop)              │
│  before_model: inject dynamic budget hint with remaining USD    │
│                (HumanMessage → cache-safe, no SystemMessage break)│
│  after_model: strip tool_calls on FINALIZATION/EXCEEDED         │
└─────────────────────────────────────────────────────────────────┘
```
