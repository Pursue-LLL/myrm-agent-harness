# publication/

## Overview
Wiki Publish Gate (WPG) SSOT. All published concept writes and indexer upserts route through
`publish_concept_article`. Pending SQLite drafts are promoted on approve via the same path.
`gate.py` adds the deterministic fail-closed routing gate: LLM-originated writes (agent tools,
chat capture) stage as pending drafts; only human origins auto-publish; unknown origins fail
closed to staging. Post-approval paths (pending approve, synthesis backlinks) and deterministic
maintenance repairs keep direct publish by design.
Move/rename reindexes via `reindex_concepts_after_move` (frontmatter-aware, no publish stamp; synchronizes referencing inbound links and graph edges).
New pending drafts demote stale published articles via `stale_guard`.
`repair_publication_status` grandfathers missing `publish_status` only; explicit draft/blocked pages are preserved.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Re-exports publish API | ✅ |
| gate.py | Core | Deterministic fail-closed publication routing: `PublicationOrigin`, `evaluate_publication_decision`, `route_concept_publication` (LLM origins stage, human origins publish) | ✅ |
| publish.py | Core | `publish_concept_article`, `repair_publication_status`, outcome types | ✅ |
| stale_guard.py | Core | Stale source detection, demote on pending stage, `StalePendingApprovalError` on approve | ✅ |
| path_change.py | Core | `ConceptPathMapping`, `reindex_concepts_after_move` for vault move/rename; skips directory sidecars and synchronizes referencing concept FTS and wiki graph edges | ✅ |

## Key Dependencies

- `core.frontmatter_contract` (type + publish_status validation/stamp)
- `core.structure` (vault paths)
- `retrieval.indexer` (FTS/Qdrant upsert on publish)
