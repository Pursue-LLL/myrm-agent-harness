# durable_budget_ledger/

## Overview
Durable spend ledger manager recovering daily budget spend accurately from persistent ledger records instead of fragile surviving messages.
Inspired by Pi's session statistics design (`packages/coding-agent/src/core/agent-session.ts:4179`) to ensure spend on rewound turns, retried messages, deleted sessions, and background keep-alive probes does not disappear on process restarts, eliminating budget underestimation risks and reconciling actual billed cost against visible branch cost.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models and DurableBudgetLedgerManager. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for DurableSpendLedgerRecord, DurableBudgetRecoverySummary, SessionActualBilledStatement, and SpendCategory. | ✅ |
| `ledger.py` | Core Manager | DurableBudgetLedgerManager managing thread-safe ledger persistence, today's spend summation, and session actual-billed reconciliation. | ✅ |
