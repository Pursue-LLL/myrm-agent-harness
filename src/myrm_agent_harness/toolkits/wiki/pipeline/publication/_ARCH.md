# publication/

## Overview
Wiki Publish Gate (WPG) SSOT. All published concept writes and indexer upserts route through
`publish_concept_article`. Pending SQLite drafts are promoted on approve via the same path.
Move/rename reindexes via `reindex_concepts_after_move` (frontmatter-aware, no publish stamp).
New pending drafts demote stale published articles via `stale_guard`.
`repair_publication_status` grandfathers missing `publish_status` only; explicit draft/blocked pages are preserved.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports publish API | ✅ |
| publish.py | Core | `publish_concept_article`, `repair_publication_status`, outcome types | ✅ |
| stale_guard.py | Core | Stale source detection, demote on pending stage, `StalePendingApprovalError` on approve | ✅ |
| path_change.py | Core | `reindex_concepts_after_move` for vault move/rename; skips directory sidecars | ✅ |

## Key Dependencies

- `core.frontmatter_contract` (type + publish_status validation/stamp)
- `core.structure` (vault paths)
- `retrieval.indexer` (FTS/Qdrant upsert on publish)
