# spend/

## Overview
Commercial spend governance and tamper-evident ledger abstraction. Provides action digest calculation for approval binding, spend parameter parsing, and protocol interfaces for append-only cryptographic ledger persistence.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public exports for spend security sub-package. | ✅ |
| `protocols.py` | Protocol | `SpendLedgerProtocol` and immutable `SpendRecordDTO` definitions. | ✅ |
| `digest.py` | Core | Cryptographic `compute_action_digest` and parameter extractor. | ✅ |
| `policy.py` | Config | `SpendPolicy` dataclass with action cap, session cap, and E-Stop checks. | ✅ |
