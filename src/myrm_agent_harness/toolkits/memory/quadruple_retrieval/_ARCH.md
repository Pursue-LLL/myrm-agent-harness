# Quadruple Parallel Retrieval and Reasoner Suite Architecture

## 1. Positioning and Boundary
- **Layer**: `myrm-agent-harness` core memory framework module.
- **Responsibility**: Pure engine providing task goal decomposition, quadruple parallel recall (Graph Topology, Dense Vector, Lexical BM25, Metadata Exact), timeout circuit breaking, RRF reciprocal rank fusion, and MMR diversity reranking.
- **No Multi-tenancy**: Strictly standalone/single-user execution engine. No business server or control-plane coupling.

## 2. Components
1. `TaskGoalParser`: Hybrid dual-track intent and entity extractor with safe fallback.
2. `QuadrupleParallelRetriever`: Concurrent retrieval orchestrator with per-channel 200ms timeout circuit breakers and graceful degradation.
3. `ReasonerHarmonizer`: Dimensionality-free RRF rank fusion combined with MMR semantic diversity deduplication.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Quadruple Parallel Retrieval and Reasoner Suite package. | ✅ |
| `goal_parser.py` | Core | Task Goal Parser decomposing queries into structured retrieval goals. | ✅ |
| `models.py` | Types | Domain models and data structures for quadruple parallel retrieval and reasoner suite. | ✅ |
| `orchestrator.py` | Core | End-to-end orchestrator executing goal-driven quadruple retrieval pipeline. | ✅ |
| `parallel_retriever.py` | Core | Quadruple parallel recall executor with multi-channel fusion and deduplication. | ✅ |
| `reasoner.py` | Core | Semantic reasoner module evaluating candidates and executing post-recall reranking. | ✅ |
