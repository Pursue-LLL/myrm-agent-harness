# graph/

## Overview
Graph Store — async graph storage with SQLite CTE backend.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Graph Store — async graph storage with SQLite CTE backend. | — |
| age_store.py | Core | Apache AGE Graph Store — enterprise-grade graph backend for SaaS deployments. | ✅ |
| base.py | Core | Graph store abstraction layer。Defines a backend-agnostic graph storage interface, data models (GraphNode, GraphRelationship, GraphQueryResult, GraphStats), and abstract methods including list_nodes/list_relationships/get_stats for visualization | ✅ |
| exceptions.py | Core | Graph store exceptions. | ✅ |
| sqlite_store.py | Core | Lightweight graph store backed by aiosqlite。Uses recursive CTE for graph queries, WAL mode, list_nodes/list_relationships/get_stats for visualization | ✅ |

## Key APIs

### get_related_nodes_with_depth(node_id, rel_type, max_depth)
Multi-hop graph traversal returning sibling nodes with their hop depth.
- Returns: `list[tuple[str, int]]` — (node_id, depth) pairs
- depth=1: direct siblings, depth=2: indirect siblings
- Used by `enrich_with_graph()` with `asyncio.gather` for parallel traversal
- Sibling scoring uses unified formula: token overlap + distance decay + freshness + importance + channel affinity
