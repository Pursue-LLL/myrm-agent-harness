# graph_arbitration/

## Overview
Automated fact conflict arbitration state machine with causal lineage tracking. Dynamic edge weight decay and frequency reinforcement operator. Semantic entity normalization and cross-session alias resolution operator.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Public facade of the graph arbitration subsystem. | ✅ |
| `arbitrator.py` | Core | Automated fact conflict arbitration state machine with causal lineage tracking. | ✅ |
| `decay.py` | Core | Dynamic edge weight decay and frequency reinforcement operator. | ✅ |
| `disambiguation.py` | Core | Semantic entity normalization and cross-session alias resolution operator. | ✅ |
| `engine.py` | Core | Unified engine for dynamic edge weighting, entity disambiguation, and conflict arbitration. | ✅ |
| `models.py` | Types | Typed entity-graph contracts for graph arbitration: fact status, conflict resolution actions, entity nodes and weighted relation edges. | ✅ |

## Key Dependencies

- External libraries: `pydantic`
