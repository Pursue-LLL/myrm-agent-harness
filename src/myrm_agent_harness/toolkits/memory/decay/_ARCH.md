# decay/

## Overview
Ebbinghaus Temporal Decay & Tiered Storage Lifecycle Engine: dynamic exponential decay scoring S(t) = I * exp(-lambda*dt) * (1 + alpha*ln(1+f)), RFM frequency boost, hot-warm-cold three-tier storage transitions, decay-aware blended retrieval reranking, and cold archive export/revival.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Ebbinghaus temporal decay and tiered storage archival lifecycle engine. | ✅ |
| `lifecycle_manager.py` | Core | Lifecycle manager governing tiered storage migration and archival. | ✅ |
| `reranker.py` | Core | Decay-aware reranker blending vector similarity with Ebbinghaus retention weights. | ✅ |
| `scorer.py` | Core | Ebbinghaus exponential decay and RFM frequency reinforcement scoring function. | ✅ |
| `types.py` | Types | Domain models and type definitions for Ebbinghaus decay and tiered storage lifecycle. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
