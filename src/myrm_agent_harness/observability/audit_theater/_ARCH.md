# audit_theater/

## Overview
Consumer-facing lie-immune audit trail theater and resource-level data access ledger suite.
Inspired by Meta Muse's catastrophic failure (lying that it only read notification previews while covertly syncing 187,000 rows of Apple iMessages).
Provides in-conversation executed actions and planned intentions, tracks granular data access across files, vector memories, MCP connectors, and remote network domains directly from authoritative backend events, certified with a cryptographic SHA-256 fingerprint.

## File Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public re-exports of models and DataAccessLedgerBuilder. | ✅ |
| `models.py` | Domain Models | Pydantic schemas for ResourceAccessEntry, TimelineAuditEvent, and SessionDataAccessLedger. | ✅ |
| `ledger_builder.py` | Core Builder | DataAccessLedgerBuilder managing authoritative resource tracking, tool inference, and SHA-256 digest hashing. | ✅ |
