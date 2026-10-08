# durable_storage/

## Overview

Portable durable storage runtime subsystem providing a unified storage contract across Memory, JSONL, and SQLite backends. Supports atomic commits with commit markers, crash reclamation, single-owner serialization, and deterministic multi-backend conformance and benchmark profiling across local, desktop, and cloud sandbox deployments.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Portable durable storage runtime package entry point. | ✅ |
| `durable_storage_protocol.py` | Protocol | Abstract interface contract governing all durable persistence backends. | ✅ |
| `durable_storage_suite.py` | Facade | Unified orchestration facade, backend factory, and deterministic benchmark runner. | ✅ |
| `durable_storage_types.py` | Types | Domain models, records, atomic write directives, and benchmark telemetry. | ✅ |
| `jsonl_durable_storage.py` | Storage | Append-only JSONL stream storage engine with commit markers and crash reclamation. | ✅ |
| `memory_durable_storage.py` | Storage | Zero-IO in-memory reference implementation of durable storage contract. | ✅ |
| `sqlite_durable_storage.py` | Storage | Relational ACID SQLite storage engine with WAL journaling and indexed query paths. | ✅ |
