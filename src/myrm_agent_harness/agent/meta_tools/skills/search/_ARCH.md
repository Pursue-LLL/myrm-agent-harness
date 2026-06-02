# search/

## Overview
Skill search module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill search module. | — |
| config_loader.py | Config | Loads external configuration for flexible synonym management. | ✅ |
| engine.py | Core | Supports query expansion for handling synonyms and typos when enabled. | — |
| hybrid_engine.py | Core | Hybrid search engine. Executes BM25 and embedding searches in parallel, fusing results with Reciproc | ✅ |
| query_expansion.py | Core | Improves search robustness through a clean, modular pipeline. | ✅ |
| query_normalizer.py | Core | Handles case normalization, punctuation removal, underscore replacement, | ✅ |
| query_parser.py | Core | - Detects "/" delimiter to identify multilingual format | ✅ |
| synonym_expander.py | Core | Loads synonyms from external YAML config if available. | ✅ |
| types.py | Config | Provides SearchMetadata, SkillSearchResult. | ✅ |
| typo_corrector.py | Core | Loads typo corrections from external YAML config if available. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
