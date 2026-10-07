# SQLite-Vec Embedded Vector Store Module Architecture

## Position
Local-first, zero-daemon, single-file embedded vector storage implementation compliant with `VectorStoreProtocol` and `VectorStore` ABC.

## Core Design Principles
1. **Zero External Daemon**: No Docker, no open network ports, no external service processes required. Everything resides within a single SQLite database file.
2. **Dual-Track Adaptive Execution**:
   - **Track A (Native SIMD)**: Loads `sqlite-vec` C-extension when available for hardware-accelerated `vec0` retrieval.
   - **Track B (Process In-Memory Fallback)**: Compact IEEE-754 float32 BLOB packing (`struct.pack`) with zero-external-dependency vector math fallback.
3. **Temporal Half-Life Decay**: Built-in `TemporalDecayScorer` attenuates stale historical memories using exponential half-life curve ($2^{-\Delta t / T_{half}}$) while preserving durable norms with importance weight multipliers and a safety score floor.
4. **Durability & Concurrency**: WAL mode journaling, synchronous=NORMAL, and connection busy timeouts ensure high concurrency and ACID guarantees.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | SQLite-vec embedded vector store package. | ✅ |
| `db.py` | Core | Database connection and low-level SQL operations for SQLite vector store. | ✅ |
| `decay.py` | Core | Temporal decay scoring engine for agent vector memories. | ✅ |
| `models.py` | Types | Data models and configuration for SQLite vector storage engine. | ✅ |
| `store.py` | Core | Single-file embedded SQLite vector store engine. | ✅ |
| `utils.py` | Core | Internal serialization and similarity utilities for SQLite vector store. | ✅ |
