# enterprise_credit_cockpit/

## Overview
Enterprise Credit and Risk Ops Cockpit Suite.
Provides a unified credit pool across product surfaces (WebUI, Desktop, Cloud Sandbox, Mobile) and establishes a consolidated audit trail linking **Actor, Timestamp, Interaction Summary, Data Object Scope, and Risk Behavior / Policy Verdict** in a single verifiable chain.

Eliminates the blindness where billing tokens and security access logs are fragmented across disconnected systems.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package Facade | Public exports for EnterpriseCreditRiskLedger, audit records, and snapshots. | ✅ |
| `models.py` | DTO & Enums | Immutable data structures for credit allocations, audit records, and risk levels. | ✅ |
| `ledger.py` | Core Ledger | Thread-safe in-memory enterprise credit pool and unified audit trail engine. | ✅ |

## Design Constraints & Principles
1. **Unified Chain (人-时-数-险同链路)**: Every credit transaction is immutably coupled with actor identity, target data object scope, and security verdict.
2. **Quota Soft/Hard Guarding**: Supports warning thresholds (e.g. 80%) and hard quota breach detection (`is_quota_breached`).
3. **Thread Safety**: Concurrent subagent runs and API transactions safely mutate shared credit allocations under lock.
4. **Strict Typing**: Zero `Any` usage across all schemas and ledger methods.
