# filters/

## Overview
Filters module.

## File & Submodule Index

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| __init__.py | Package | Filters module. | — |
| base.py | Core | Filter base class definition. Defines the filter interface (BaseFilter), data structures (FilterCont | ✅ |
| prompts.py | Core | Prompts. | ✅ |
| semantic_filter.py | Core | Semantic filter. Uses LLM to describe the structure and key points of unstructured content (HTML/Mar | ✅ |
| structural_filter.py | Core | Structural data filter. Extracts structure from JSON/XML/code/CSV/YAML/log files using pure code wit | ✅ |

## Key Dependencies

- `utils`
