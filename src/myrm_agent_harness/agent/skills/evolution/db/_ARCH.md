# db/

## Overview
Agent Skills Evolution Db module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package |   Init   | — |
| store.py | Core | SQLite persistence for skill evolution system — DDL, lifecycle, CRUD, eval_cases persistence. Content length guard: `save_skill` / `save_skills_batch` reject records whose content exceeds `MAX_SKILL_CONTENT_CHARS` (ValueError) so oversized skills never silently fail vectorization and become undiscoverable. Inherits vector sync from `_store_vector`, evolution tracking from `_store_evolution_tracking`, and dependency graph persistence from `_store_dependencies`. | ✅ |
| store_queries.py | Core | Complex query methods for SkillStore, including Hybrid Retrieval (Semantic Search). | ✅ |
| _store_vector.py | Internal | Vector store synchronization mixin for SkillStore — Qdrant sync, embed, delete. | ✅ |
| _store_evolution_tracking.py | Internal | Evolution tracking persistence mixin — execution analyses, rejections, constraints. | ✅ |
| _store_dependencies.py | Internal | Persistent skill dependency tracking mixin — resolves frontmatter `dependencies`/body tool markers at write time into `skill_dependencies` edges, exposes `get_dependents` / `get_dependents_map` / `get_skill_dependencies` for impact analysis. | ✅ |
