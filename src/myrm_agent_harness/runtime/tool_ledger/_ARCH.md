# tool_ledger/

## Overview
Durable tool run ledger and cost-aware pre-retry reconciliation suite.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Durable tool run ledger and cost-aware pre-retry reconciliation suite. | — |
| `durable_tool_ledger.py` | Core | SQLite-backed durable tool run ledger and result artifact deduplicator. | ✅ |
| `ledger_types.py` | Core | Strongly typed data contracts for durable tool run ledger and pre-retry reconciliation. | ✅ |
| `pre_retry_reconciler.py` | Core | Pre-retry action audit reconciler and card renderer. | ✅ |
| `stream_db_reconciler.py` | Core | Stream tail and persistent DB reconciler with lossy reasoning deduplication. | ✅ |
