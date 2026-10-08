# graph_reorganization/

## Overview

Graph Memory Reorganization and Lineage Traceability Suite.
Synthesizes multi-relational edges (subsumption, temporal sequence, deduction, contradiction)
and maintains an immutable lineage DAG (supersedes, derived_from) preventing memory amnesia and rough overwrites.

## File & Submodule Index

| File | Role | Description | I/O/P |
| --- | --- | --- | --- |
| __init__.py | Package | Graph memory reorganization and lineage traceability suite package. | ✅ |
| models.py | Core | Domain models and data structures for graph memory reorganization and lineage traceability. | ✅ |
| detector.py | Core | Multi-relational detector scanning candidate edges across memory graph nodes. | ✅ |
| lineage_engine.py | Core | Engine managing memory lineage tracker, DAG traversal, and version rollbacks. | ✅ |
| reorganizer.py | Core | Graph memory reorganization engine synthesizing multi-relational edges and managing supersession. | ✅ |
