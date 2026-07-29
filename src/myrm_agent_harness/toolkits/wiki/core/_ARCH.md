# core/

## Overview
Wiki core configuration, types, and file structure management. Includes purpose-driven
knowledge direction, compile/query configs, and recursive file system operations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| config.py | Config | WikiConfig, WikiQueryConfig (incl. index_first/sidecar/best-first/raw_claim knobs), WikiCompileConfig | ✅ |
| parsers.py | Core | LLM response parsers — JSON and bullet-point format to ConceptInfo list | ✅ |
| structure.py | Core | File system layout, OKF paths, `get_index_catalog_relative_path()`, directory sidecar helpers, tree CRUD | ✅ |
| types.py | Types | Data models: ConceptInfo, WikiArticle, CompileResult (incl. publication counts), SourceSnippet (incl. claim citation + `evidence_snapshot_status`), LintIssue, LintResult | ✅ |
| frontmatter_contract.py | Contract | WikiPageType + WikiPublishStatus; validate/infer/repair `type`; yaml-aware `load_frontmatter_metadata` / `serialize_frontmatter_block`; `repair_publication_on_disk` grandfathers missing publish_status only (skips draft/blocked) | ✅ |
| claims_contract.py | Contract | OC-compatible structured `claims` parse/validate/merge; compile-time evidence `contentSha256` pin; read-time `resolve_evidence_snapshot_status`; `ensure_compile_claims` with honest fallback (`unknown`) | ✅ |
| section_contract.py | Contract | Managed block SSOT: extract/replace/append + `parse_editor_sections` for GUI | ✅ |
| canonical_registry.py | Contract | `canonical_id` / alias index, page lease hash, write-time dedup helpers | ✅ |
| refactor.py | Core | LinkRefactorEngine — update relative markdown links when wiki files move or rename | ✅ |
