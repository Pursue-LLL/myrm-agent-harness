# core/

## Overview
Wiki core configuration, types, and file structure management. Includes purpose-driven
knowledge direction, compile/query configs, and recursive file system operations.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Init | — |
| config.py | Config | WikiConfig (purpose, compile strategy), WikiCompileConfig (provenance prompts), WikiQueryConfig | ✅ |
| parsers.py | Core | LLM response parsers — JSON and bullet-point format to ConceptInfo list | ✅ |
| structure.py | Core | File system layout (raw/, wiki/, concepts/, purpose.md), OKF cognitive map paths (`index.md`/`log.md`/`hot.md`), directory sidecar path helpers (`.abstract.md`/`.overview.md`), tree CRUD, `delete_folder_safe` with indexer sync | ✅ |
| types.py | Types | Data models: ConceptInfo, WikiArticle, CompileResult (incl. publication counts), LintIssue, LintResult | ✅ |
| frontmatter_contract.py | Contract | WikiPageType + WikiPublishStatus enums; validate/infer/repair frontmatter `type`; `repair_publication_on_disk` grandfathers missing publish_status only (skips draft/blocked) | ✅ |
| refactor.py | Core | LinkRefactorEngine — update relative markdown links when wiki files move or rename | ✅ |
