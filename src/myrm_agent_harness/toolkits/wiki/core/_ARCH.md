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
| structure.py | Core | File system layout (raw/, wiki/, concepts/, purpose.md), tree CRUD, `delete_folder_safe` with indexer sync | ✅ |
| types.py | Types | Data models: ConceptInfo, WikiArticle, CompileResult, LintIssue, LintResult | ✅ |
| refactor.py | Core | LinkRefactorEngine — update relative markdown links when wiki files move or rename | ✅ |
