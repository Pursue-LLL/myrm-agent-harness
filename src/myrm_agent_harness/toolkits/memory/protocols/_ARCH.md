# protocols/

## Overview
Storage-agnostic protocols for the memory system.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Storage-agnostic protocols for the memory system. | — |
| cache.py | Core | Embedding cache protocol — optional caching layer. | ✅ |
| conversation_search.py | Core | Storage-agnostic conversation search provider protocol consumed by the recall tool. | ✅ |
| embedding.py | Core | Embedding protocol — text to vector abstraction. | ✅ |
| graph.py | Core | Memory-system graph store protocol。Defines the graph operation interface required by the memory module, including list_nodes/list_relationships/get_stats for visualization, exports GraphNode, GraphRelationship, GraphStats | ✅ |
| hooks.py | Core | Memory lifecycle hook protocol. Defines optional provider callbacks for turn start, pre-compression, writes, delegation, and session end. | ✅ |
| relational.py | Core | Relational store protocol. Defines the relational storage interface for Profile, Procedural, | ✅ |
| vector.py | Core | Memory-system vector store protocol. Defines the vector operation interface required by the memory m | ✅ |
