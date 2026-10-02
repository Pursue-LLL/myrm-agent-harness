# qdrant/

## Overview
Qdrant Vector Store — built-in implementation.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Qdrant Vector Store — built-in implementation. | — |
| factory.py | Core | Qdrant factory module. Manages singleton instances for embedded mode and AsyncQdrantClient creation; `evict_embedded_store` / `clear_embedded_stores` release per-path embedded singletons when throwaway volumes (isolated eval runs, shutdown) are done. Unwritable paths fall back to `:memory:` with a cache key derived from the original path (`f"{path}:memory_fallback"`) so distinct base_paths never share one in-memory instance; repeated calls re-check the fallback key before creating (singleton preserved), and `evict_embedded_store` probes both keys. If the `:memory:` fallback itself fails, the original disk error is preserved in a `RuntimeError` chain (both failures reported) | ✅ |
| filters.py | Core | Qdrant filter builder. Converts generic dict filter syntax to Qdrant SDK Filter objects, including datetime range detection, point ID queries, MatchExcept/MatchValue, and not conditions. | ✅ |
| sparse.py | Core | Qdrant sparse-vector operations (`QdrantSparseMixin` hosted by `QdrantVectorStore`). Ensures/creates sparse-only collections (named `bm25` vector, single-shot create so concurrent 409s fail fast), upserts sparse points, and queries the named vector with server-side IDF scoring. All client access goes through `_execute` so sync (embedded) and async (remote) clients work alike. | ✅ |
| store.py | Core | Qdrant vector store implementation. Supports embedded and remote deployment modes with built-in retry; hosts `QdrantSparseMixin` for the persistent BM25 sparse channel; `point_id_for` normalizes any id into a valid UUIDv4 point id (shared by dense and sparse upserts). `hard_close` force-closes the client when a store is evicted from the embedded singleton cache. Overrides `VectorStore.is_persistent` as `local_path != ":memory:"` — embedded stores degraded to `:memory:` report non-persistent so callers can surface the ephemeral mode. Implements `ensure_collection` (idempotent create-if-missing) to satisfy the memory `VectorStoreProtocol` contract used by recurrence strategies | ✅ |
