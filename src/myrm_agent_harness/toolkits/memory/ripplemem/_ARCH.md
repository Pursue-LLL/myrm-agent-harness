# ripplemem/

## Overview
RippleMem Sparse Event Graph & Budgeted Active Recall Controller: normalized event units m=(r, v, p, l, t, c), dual-edge sparse graph indexing with super-node degree pruning & temporal decay, saturation fast-path gate, and bounded directional ripple spreading.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Exports normalized event modeling, dual-edge sparse graph indexing, and active recall controller engines for multi-session distributed evidence reasoning. | ✅ |
| `event_extractor.py` | Core | Extracts atomic self-contained event units with pronoun resolution, temporal anchoring, and typed clue slot parsing for sparse graph population. | ✅ |
| `models.py` | Types | Domain models defining atomic normalized event units, sparse graph topology, and active recall controller payloads for multi-session distributed reasoning. | ✅ |
| `recall_controller.py` | Core | Brain of the RippleMem architecture. | ✅ |
| `sparse_graph.py` | Core | Maintains semantic and structural edges connecting normalized event units. | ✅ |

## Key Dependencies

- None (self-contained within the package and the standard library)
