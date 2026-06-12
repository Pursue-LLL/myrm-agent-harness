# hybrid_search/

## Overview
Hybrid retrieval module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Hybrid retrieval module. | — |
| coordinator.py | Core | Provides HybridSearchCoordinator. | ✅ |
| fusion_pipeline.py | Core | Result fusion pipeline: dedup → orthogonal fusion → Autocut dynamic truncation → top-k. | ✅ |
| reranking_pipeline.py | Core | Provides RerankingPipeline. | ✅ |

## Key Dependencies

- `utils`
