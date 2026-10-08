# nested_approval_restore/

## Overview

Subsystem ensuring that live approval decisions (especially permanent rejections) take precedence over stale historical snapshots during nested agent restoration, while providing transactional compaction replacement with bounded rollback budgets.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Nested approval restoration and compaction rollback package entry point. | ✅ |
| `approval_precedence_resolver.py` | Core | Precedence resolver enforcing live-decision priority over stale snapshot approvals. | ✅ |
| `compaction_rollback_buffer.py` | Core | Compaction buffer implementing validate-before-purge and bounded rollback stash. | ✅ |
| `nested_approval_restore_suite.py` | Core | Unified facade suite managing nested approvals, live priority, and compaction rollback. | ✅ |
| `nested_approval_types.py` | Types | Domain contracts, decision models, and receipts for nested approval restoration. | ✅ |
