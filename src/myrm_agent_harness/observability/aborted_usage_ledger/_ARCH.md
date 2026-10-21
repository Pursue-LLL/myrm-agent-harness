# aborted_usage_ledger/

## Overview
Canonical usage ledger manager preventing pseudo-free zero-token representations on aborted auxiliary model calls.
Inspired by Maka-Agent PR #5890 and commit `3bd8bbe1e5` to ensure aborted auxiliary calls (summarization, compaction, audit, routing) without provider usage payloads are explicitly marked as `usage-unknown`, strictly isolating them from known token consumption and cost aggregations.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models and CanonicalUsageLedgerManager. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for CanonicalUsageLedgerRow, AbortedUsageUnknownStats, UsageAvailabilityKind, LedgerCallStatus, and AuxiliaryCallKind. | ✅ |
| `ledger.py` | Core Manager | CanonicalUsageLedgerManager managing thread-safe ledger ingestion, usage-unknown enforcement, and transparent risk stats aggregation. | ✅ |
