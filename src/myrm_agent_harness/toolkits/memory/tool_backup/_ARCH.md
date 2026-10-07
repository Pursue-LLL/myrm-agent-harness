# Durable Tool Use Backup Index Architecture

## Overview
This package implements a high-performance SQLite side index for raw tool input/output observations (Item 74). It decouples verbatim tool interaction evidence from ephemeral L2 context compaction/summarization, providing an immutable audit and reflection trail for L3 memory distillation.

## Core Modules
- `models.py`: Strongly typed primitives (`ToolUseRecord`, `ToolUseStatus`, `ToolUseQueryFilter`, `ToolUseStats`).
- `db.py`: `ToolUseDatabase` managing SQLite tables, WAL mode, and session/tool indexes.
- `recorder.py`: `ToolUseBackupRecorder` providing fail-safe side indexing with payload truncation protection.
- `store.py`: `DurableToolUseStore` delivering by-reference lookups, filtered range queries, and audit statistics.
- `service.py`: `ToolUseBackupService` unified facade integrating database, recorder, and query store.
- `__init__.py`: Public package exports conforming to harness conventions.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for tool backup. | ✅ |
| `db.py` | Core | Manages SQLite schema and connection configuration for durable tool use index. | ✅ |
| `models.py` | Types | Types and models for tool backup. | ✅ |
| `recorder.py` | Core | Fail-safe side-index recorder capturing exact tool inputs and outputs. | ✅ |
| `service.py` | Core | Unified facade service orchestrating durable tool use logging and audit lookups. | ✅ |
| `store.py` | Core | Query and management store for durable side-indexed tool executions. | ✅ |
