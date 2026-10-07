# Batch Memory Learning and Namespaced ID Provenance Architecture

## 1. Positioning and Boundaries
The `batch_learn` module in `myrm-agent-harness` provides resilient, chunk-level knowledge extraction with per-item namespaced IDs and undo capabilities.

- **Non-blocking chunk boundaries**: Transient errors (HTTP 429, 503, socket timeouts) on individual chunks are mitigated via exponential backoff with full jitter, preventing the failure of the entire batch.
- **Per-item namespaced ID contract**: Every extracted memory receives a structured identifier `mem:{scope}:{sub_scope}:{category}:{content_fingerprint}`, enabling unambiguous provenance, UI deep-linking, and single-item revocation.
- **Single-machine SQLite audit ledger**: Persists runs, chunk diagnostics, and learned items locally with zero multi-tenant dependencies.

## 2. Component Structure
- `models.py`: Strongly-typed domain models for chunks, items, IDs, diagnostics, and retry configs.
- `id_generator.py`: Deterministic namespaced identifier generation, parsing, and format validation.
- `resilient_executor.py`: Transient error classification and exponential backoff retry executor.
- `service.py`: SQLite-backed orchestration service managing batch runs, item storage, and revocation.
- `tools.py`: Agent-facing meta-tools allowing LLM agents to perform batch extraction, inspect items, and revoke memories.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for batch learn. | ✅ |
| `id_generator.py` | Core | Industrial-grade namespaced ID generator ensuring cross-session uniqueness and unambiguous provenance. | ✅ |
| `models.py` | Types | Types and models for batch learn. | ✅ |
| `resilient_executor.py` | Core | Executes chunk-level extraction logic with isolated retry boundaries and jittered backoff. | ✅ |
| `service.py` | Core | Core service providing item-level namespaced provenance and resilient chunk batch extraction. | ✅ |
| `tools.py` | Core | Agent meta-tools for batch memory ingestion with item-level namespaced ID provenance and undo. | ✅ |
