# db/

## Overview
Agent Skills Evolution Db module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| store.py | Core | SQLite persistence for skill evolution system — DDL, lifecycle, CRUD. Inherits vector sync from `_store_vector` and evolution tracking from `_store_evolution_tracking`. | ✅ |
| store_queries.py | Core | Complex query methods for SkillStore, including Hybrid Retrieval (Semantic Search). | ✅ |
| _store_vector.py | Internal | Vector store synchronization mixin for SkillStore — Qdrant sync, embed, delete. | ✅ |
| _store_evolution_tracking.py | Internal | Evolution tracking persistence mixin — execution analyses, rejections, constraints. | ✅ |
