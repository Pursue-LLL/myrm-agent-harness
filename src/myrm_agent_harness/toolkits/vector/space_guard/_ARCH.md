# Vector Space Consistency Guard Module Architecture

## 1. Position and Boundary
- **Layer**: `myrm-agent-harness` core vector storage toolkit subpackage.
- **Responsibility**: Pre-flight validation gate ensuring embedding model dimension, base coordinate space, and distance metric integrity across vector storage operations.
- **No Multi-tenancy**: Strictly standalone/single-user execution engine. No business server or control-plane coupling.

## 2. Core Components
1. `EmbeddingModelFingerprint`: Strongly typed model signature (provider, model name, dimension, metric, deterministic SHA256 configuration hash).
2. `VectorSpaceMetadata`: Persistent binding between a vector collection and its canonical model fingerprint.
3. `VectorSpaceGuard`: Pre-flight consistency guard validating runtime embedding model against collection space fingerprint with fallback recommendation.
4. `VectorSpaceReindexer`: Coordinates migration of vector collections when switching embedding models.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Vector space consistency guard package. | ✅ |
| `guard.py` | Core | Vector space consistency guard implementation and pre-flight validation. | ✅ |
| `models.py` | Types | Data contracts and exceptions for vector space consistency guard. | ✅ |
| `reindexer.py` | Core | Reindexing orchestrator for migrating vector collections to new embedding models. | ✅ |
