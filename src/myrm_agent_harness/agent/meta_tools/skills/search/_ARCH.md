# search/

## Overview
Skill search module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Skill search module. | — |
| config_loader.py | Config | Loads external configuration for flexible synonym management. | ✅ |
| engine.py | Core | BM25 + regex skill search; MCP skills with >3 tools get tool-level index enrichment; QueryExpander on by default. | ✅ |
| hybrid_engine.py | Core | Hybrid search (BM25 + embedding, RRF). Lazy-imports numpy; missing numpy raises RuntimeError pointing to `[retrieval]`. | ✅ |
| query_expansion.py | Core | Improves search robustness through a clean, modular pipeline. | ✅ |
| query_normalizer.py | Core | Handles case normalization, punctuation removal, underscore replacement, | ✅ |
| query_parser.py | Core | - Detects "/" delimiter to identify multilingual format | ✅ |
| synonym_expander.py | Core | Synonym expansion with whole-word English matching and YAML-backed mappings. | ✅ |
| types.py | Config | Provides SearchMetadata, SkillSearchResult. | ✅ |
| typo_corrector.py | Core | Loads typo corrections from external YAML config if available. | ✅ |

## Key Dependencies

- `backends`
- `toolkits`
- Optional: `myrm-agent-harness[retrieval]` (numpy for vector index paths in `hybrid_engine.py`)
