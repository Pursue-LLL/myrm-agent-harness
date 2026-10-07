# Temporal Knowledge Graph & Decay Conflict Resolution Suite Architecture

## 1. Positioning & Overview
The `temporal_graph` package implements time-aware knowledge graph memory with dynamic weight decay and fact reconciliation for `myrm-agent-harness`.
Inspired by `Graphiti` and `OpenViking`, it solves the core challenge where user preferences, company affiliations, and tech stacks evolve dynamically over time, preventing contradiction deadlocks and hallucinations.

## 2. Key Components
1. **`models.py`**:
   - `TemporalEntityNode`: Named entities (users, tech stacks, organizations).
   - `TemporalFactEdge`: Directed relational facts with validity windows (`valid_from`, `valid_until`), confidence scores, and supersession pointers (`is_superseded`, `superseded_by`).
   - `FactConflictResolutionResult`: Detailed report when mutual exclusion conflicts trigger supersession.
   - `TemporalFactHit`: Decayed score rankings for snapshot traversals.
2. **`decay_scorer.py` (`TemporalDecayScorer`)**:
   - Computes exponential half-life decay ($2^{-\Delta t / t_{\text{half}}}$) combined with retrieval access reinforcement bonuses.
   - Categorizes edges into `active`, `superseded`, and `expired`.
3. **`sqlite_store.py` (`SqliteTemporalGraphStore`)**:
   - Local-first thread-safe SQLite backend with composite indexes on `(source_id, predicate, is_superseded)`.
4. **`conflict_reconciler.py` (`TemporalFactConflictReconciler`)**:
   - Identifies mutually exclusive predicates (`works_at`, `current_framework`, etc.).
   - Automatically and atomically supersedes historical facts instead of destructively deleting them, retaining chronological evolutionary lineage.

## 3. Boundary & Non-Goals
- **Non-Goals**: No distributed multi-tenant storage, no heavy external graph database dependencies (e.g. Neo4j).
- **Zero Any**: All interfaces use concrete type annotations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Package facade for temporal graph. | ✅ |
| `conflict_reconciler.py` | Core | Detects and resolves fact contradictions by marking superseded edges in temporal memory. | ✅ |
| `decay_scorer.py` | Core | Calculates exponential half-life decay and access reinforcement for temporal graph edges. | ✅ |
| `models.py` | Types | Types and models for temporal graph. | ✅ |
| `sqlite_store.py` | Core | Thread-safe SQLite storage for temporal knowledge graph entities and edges. | ✅ |
