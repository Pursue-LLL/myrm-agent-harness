# Memory Governance Architecture

## 1. Overview
The Memory Governance module implements a unified four-dimensional memory architecture:
- **Profile Slots**: Structured key-value slots (persona, preferences, constraints, custom). Serialized with strict lexicographical key ordering to maximize LLM Prompt Cache hit rates.
- **Event Timeline**: Chronological event logs recording state transitions and user interactions.
- **Dynamic Facts**: Volatile and stateful facts managed with TTL expiration and 4-state reconciliation (ADD, UPDATE, DELETE, NOOP).
- **Entity Graph**: Two-hop bounded relationship traversal backed by `SQLiteGraphStore` (CTE-based recursive query) to prevent combinatorial explosion.

## 2. Component Structure
- `models.py`: Immutable and mutable domain entities, enum definitions, and context representations.
- `reconciler.py`: Four-state conflict reconciliation engine with pluggable or rule-based resolvers and TTL pruner.
- `graph_bridge.py`: Strict radius-limited bridge to `GraphStore` (`depth <= 2`, `max_nodes <= 15`).
- `assembler.py`: Budget-aware context assembler generating deterministic, high-cache-rate system prompts.

## 3. Design Principles & Hard Boundaries
- **No Multi-Tenancy**: Pure single-agent execution in sandbox. Zero tenant IDs or foreign multi-tenant constructs.
- **Prompt Cache Priority**: Profile slot prefixes must guarantee identical text representations across sessions when data is unchanged.
- **Strict Typing**: Zero `Any` types across all methods and models.
